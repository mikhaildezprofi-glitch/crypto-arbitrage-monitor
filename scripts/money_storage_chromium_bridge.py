"""Human-operated Chromium bridge for Money Storage E-ID and read-only quote capture.

Normal mode observes the page's own authenticated offers request and validates
the captured response. Return-only, form-inspection, and isolated session-check
modes remain explicit access-diagnostic modes.

It does not automate clicks, solve challenges, export cookies, or persist
browser credentials.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import websocket

# Running a file from scripts/ puts that directory, not the repository root,
# at sys.path[0]. Add the checkout root and src/ for project imports.
sys.path.insert(0, str(Path.cwd()))
sys.path.insert(0, str(Path.cwd() / "src"))

from scripts.money_storage_cloud_read import (
    TransientMoneyStorageReadError,
    fetch_from_authenticated_page,
    write_normalized_snapshot,
)
from arbitrage_monitor.providers.money_storage_access import (
    classify_cloudflare_challenge,
    classify_money_storage_page,
    is_money_storage_auth_failure,
    is_money_storage_authenticated_offers_page,
    has_returned_to_money_storage,
)

DEBUG_ENDPOINT = "http://127.0.0.1:9222/json/list"
STATUS_FILE = Path(os.environ.get("MONEY_STORAGE_STATUS_FILE", "/tmp/eid-auth-status"))
SESSION_CHECK = os.environ.get("MONEY_STORAGE_SESSION_CHECK") == "1"
NONINTERACTIVE = os.environ.get("MONEY_STORAGE_NONINTERACTIVE") == "1"
RETURN_ONLY = os.environ.get("MONEY_STORAGE_RETURN_ONLY") == "1"
FORM_INSPECTION = os.environ.get("MONEY_STORAGE_FORM_INSPECTION") == "1"
DEADLINE_SECONDS = 180 if SESSION_CHECK or NONINTERACTIVE else 1800


def safe_location(value: str) -> str:
    try:
        parsed = urlparse(value)
        return f"{parsed.netloc}{parsed.path}"
    except Exception:
        return "unparseable"


class CDP:
    def __init__(self, ws_url: str):
        self.ws = websocket.create_connection(
            ws_url, timeout=3, suppress_origin=True, enable_multithread=True
        )
        self.next_id = 0
        self.main_frame_id: str | None = None
        self.storage_document_status: int | None = None
        self.storage_document_path: str | None = None
        self.current_document_cf_challenge = False
        self.saw_eid_navigation = False

    def close(self) -> None:
        self.ws.close()

    def _event(self, message: dict) -> None:
        method = message.get("method", "")
        params = message.get("params", {})

        if method == "Network.requestWillBeSent" and FORM_INSPECTION:
            request = params.get("request", {})
            parsed = urlparse(request.get("url", ""))
            request_type = str(params.get("type", "unknown")).lower()
            if (
                parsed.hostname == "storage.money"
                and (parsed.path == "/public_deals/fetch" or request_type in ("xhr", "fetch"))
            ):
                query = parse_qs(parsed.query)
                body = request.get("postData", "")
                body_fields = {}
                if body:
                    try:
                        decoded = json.loads(body)
                        if isinstance(decoded, dict):
                            body_fields = decoded
                    except (TypeError, ValueError):
                        try:
                            body_fields = parse_qs(body)
                        except Exception:
                            body_fields = {}
                def field_value(name: str) -> str:
                    value = query.get(name, body_fields.get(name, [""]))
                    if isinstance(value, list):
                        value = value[0] if value else ""
                    return str(value).strip().upper()[:16]
                source = field_value("from")
                target = field_value("to")
                print(
                    "PAGE_REQUEST host=storage.money path=%s type=%s method=%s from=%s to=%s pair_location=%s"
                    % (
                        parsed.path,
                        request_type,
                        request.get("method", "unknown"),
                        source or "absent",
                        target or "absent",
                        "query" if query.get("from") or query.get("to") else ("body" if body_fields else "none"),
                    ),
                    flush=True,
                )
                if source == "ECR" and target == "USDT":
                    STATUS_FILE.write_text("FORM_INSPECTION_COMPLETE", encoding="utf-8")

        elif method == "Page.frameNavigated":
            frame = params.get("frame", {})
            if not frame.get("parentId"):
                self.main_frame_id = frame.get("id")
                self.current_document_cf_challenge = False
                frame_url = frame.get("url", "")
                frame_host = (urlparse(frame_url).hostname or "").lower()
                if frame_host == "e-id.cards" or frame_host.endswith(".e-id.cards"):
                    self.saw_eid_navigation = True
                location = safe_location(frame_url)
                print(f"NAV={location}", flush=True)

        elif method == "Network.responseReceived":
            response = params.get("response", {})
            parsed = urlparse(response.get("url", ""))
            host = (parsed.hostname or "").lower()
            if FORM_INSPECTION and host == "storage.money" and (
                parsed.path == "/public_deals/fetch"
                or params.get("type", "").lower() in ("xhr", "fetch")
            ):
                headers = {str(k).lower(): str(v) for k, v in response.get("headers", {}).items()}
                print(
                    "PAGE_RESPONSE path=%s status=%s type=%s content_type=%s request_id=%s"
                    % (
                        parsed.path,
                        int(response.get("status", 0)),
                        params.get("type", "unknown").lower(),
                        headers.get("content-type", "absent").split(";")[0],
                        str(params.get("requestId", ""))[:32],
                    ),
                    flush=True,
                )
            if not (
                host == "storage.money"
                or host.endswith(".storage.money")
                or host == "e-id.cards"
                or host.endswith(".e-id.cards")
                or "cloudflare" in host
            ):
                return
            headers = {str(k).lower(): str(v) for k, v in response.get("headers", {}).items()}
            status = int(response.get("status", 0))
            content_type = headers.get("content-type", "absent").split(";")[0]
            ray = headers.get("cf-ray", "absent")
            mitigated = headers.get("cf-mitigated", "absent")
            server = headers.get("server", "absent")
            kind = params.get("type", "unknown").lower()
            # Only a challenge response for the top-level document can mark
            # the current page as challenged. Turnstile iframe requests must
            # not leave a sticky page-level challenge flag after the widget clears.
            if kind == "document" and params.get("frameId") == self.main_frame_id and (
                mitigated.lower() == "challenge"
                or "/cdn-cgi/challenge-platform/" in parsed.path
            ):
                self.current_document_cf_challenge = True
            if host == "storage.money" and kind == "document":
                self.storage_document_status = status
                self.storage_document_path = parsed.path
            print(
                "HTTP_DIAG host=%s path=%s status=%s type=%s server=%s "
                "cf_ray=%s cf_mitigated=%s content_type=%s"
                % (host, parsed.path, status, kind, server, ray, mitigated, content_type),
                flush=True,
            )
            if mitigated.lower() == "challenge" or "/cdn-cgi/challenge-platform/" in parsed.path:
                print("CLOUDFLARE_CHALLENGE_DETECTED=YES", flush=True)
            if status in (401, 403, 429, 503):
                print(f"ACCESS_RESPONSE_CLASSIFICATION host={host} status={status}", flush=True)

    def command(self, method: str, params: dict | None = None, timeout: float = 15) -> dict:
        self.next_id += 1
        command_id = self.next_id
        self.ws.send(json.dumps({"id": command_id, "method": method, "params": params or {}}))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                raw = self.ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            message = json.loads(raw)
            if "method" in message:
                self._event(message)
            if message.get("id") == command_id:
                if "error" in message:
                    raise RuntimeError(f"CDP command {method} failed: {message['error'].get('message', 'unknown error')}")
                return message.get("result", {})
        raise TimeoutError(f"CDP command timed out: {method}")

    def evaluate(self, expression: str, await_promise: bool = True):
        result = self.command(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": await_promise,
                "returnByValue": True,
                "userGesture": False,
            },
        )
        if "exceptionDetails" in result:
            details = result["exceptionDetails"]
            raise RuntimeError(f"Browser evaluation failed: {details.get('text', 'JavaScript exception')}")
        remote = result.get("result", {})
        if remote.get("subtype") == "error":
            raise RuntimeError("Browser evaluation returned a JavaScript error.")
        return remote.get("value")


class CDPPage:
    """Minimal adapter for the existing authenticated-page reader."""

    def __init__(self, cdp: CDP):
        self.cdp = cdp

    @property
    def url(self) -> str:
        return self.cdp.evaluate("location.href", await_promise=False)

    def evaluate(self, script: str, argument=None):
        expression = f"({script})({json.dumps(argument, ensure_ascii=False)})"
        return self.cdp.evaluate(expression, await_promise=True)


def page_targets() -> list[dict]:
    request = urllib.request.Request(DEBUG_ENDPOINT, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=3) as response:
        data = json.loads(response.read().decode("utf-8"))
    return [item for item in data if item.get("type") == "page" and item.get("webSocketDebuggerUrl")]


def connect_to_chromium() -> CDP:
    deadline = time.monotonic() + 120
    last_error = "no page target"
    while time.monotonic() < deadline:
        try:
            targets = page_targets()
            if targets:
                # Never fall back to another site's tab: that can hijack one of
                # the other shared-browser pages when probes start together.
                target = next(
                    (item for item in targets
                     if urlparse(item.get("url", "")).hostname == "storage.money"
                     and urlparse(item.get("url", "")).path.rstrip("/") == "/deals"),
                    None,
                )
                if target:
                    print("CHROMIUM_TAB_BINDING=storage.money/deals TARGET_ID=" +
                          str(target.get("id", "unknown")), flush=True)
                    return CDP(target["webSocketDebuggerUrl"])
        except Exception as exc:
            last_error = type(exc).__name__
        time.sleep(1)
    raise RuntimeError(f"Could not attach to the visible Chromium page: {last_error}")


def page_state(cdp: CDP) -> tuple[str, str, str]:
    value = cdp.evaluate(
        """(() => ({
          url: location.href,
          title: document.title || "",
          body: document.body ? document.body.innerText.slice(0, 12000).toLowerCase() : ""
        }))()"""
    )
    return value.get("url", ""), value.get("title", ""), value.get("body", "")


def deals_form_diagnostics(cdp: CDP) -> dict:
    """Return visible, non-secret currency-form metadata without changing the page."""
    result = cdp.evaluate(
        """(() => {
          const visible = element => {
            const style = getComputedStyle(element);
            const rect = element.getBoundingClientRect();
            return style.visibility !== "hidden" && style.display !== "none"
              && rect.width > 0 && rect.height > 0;
          };
          const clean = value => String(value || "").replace(/\\s+/g, " ").trim().slice(0, 120);
          const fields = Array.from(document.querySelectorAll("select, [role=combobox], input"))
            .filter(visible).slice(0, 40).map(element => {
              const item = {
                tag: element.tagName.toLowerCase(),
                id: clean(element.id),
                name: clean(element.getAttribute("name")),
                role: clean(element.getAttribute("role")),
                ariaLabel: clean(element.getAttribute("aria-label")),
                type: clean(element.getAttribute("type")),
                placeholder: clean(element.getAttribute("placeholder"))
              };
              if (element.tagName === "SELECT") {
                item.selectedText = clean(element.selectedOptions?.[0]?.textContent);
                item.selectedValue = clean(element.value);
                item.options = Array.from(element.options).slice(0, 30).map(option => ({
                  text: clean(option.textContent),
                  value: clean(option.value),
                  selected: option.selected
                }));
              }
              return item;
            });
          const currencyHint = /(USDT|ECR|ERUB|CNY|RUB|USD|EUR|валют|currency|give|receive|отда|получ)/i;
          const buttons = Array.from(document.querySelectorAll("button, [role=button], [role=option]"))
            .filter(visible).map(element => ({
              text: clean(element.innerText || element.textContent),
              ariaLabel: clean(element.getAttribute("aria-label")),
              title: clean(element.getAttribute("title"))
            }))
            .filter(item => currencyHint.test(item.text + " " + item.ariaLabel + " " + item.title))
            .slice(0, 40);
          return { fields, currencyControls: buttons };
        })()"""
    )
    if not isinstance(result, dict):
        result = {"unavailable": True}
    print("PAGE_DIAG deals_form=" + json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
    return result


def click_official_eid_action(cdp: CDP) -> dict:
    """Open only a visible Money Storage link that explicitly targets e-id.cards."""
    result = cdp.evaluate(
        """(() => {
          const visible = element => {
            const style = getComputedStyle(element);
            const rect = element.getBoundingClientRect();
            return style.visibility !== "hidden" && style.display !== "none"
              && rect.width > 0 && rect.height > 0;
          };
          const links = Array.from(document.querySelectorAll("a[href]")).filter(visible);
          for (const link of links) {
            const label = String(link.innerText || link.textContent || "")
              .replace(/\\s+/g, " ").trim().slice(0, 120);
            let target;
            try { target = new URL(link.href, location.href); } catch (_) { continue; }
            const host = target.hostname.toLowerCase();
            const officialHost = host === "e-id.cards" || host.endsWith(".e-id.cards");
            if (/e[\\s-]?id/i.test(label) && target.protocol === "https:" && officialHost) {
              link.click();
              return { clicked: true, label, host, path: target.pathname };
            }
          }
          return { clicked: false };
        })()"""
    )
    return result if isinstance(result, dict) else {"clicked": False}


def main() -> int:
    STATUS_FILE.write_text("WAITING_FOR_LOGIN", encoding="utf-8")
    cdp = connect_to_chromium()
    try:
        cdp.command("Page.enable")
        cdp.command("Runtime.enable")
        cdp.command("Network.enable")
        # Capture the offers JSON from the page's own authenticated fetch. The
        # response is cloned asynchronously; the original response is untouched.
        if not SESSION_CHECK and not RETURN_ONLY and not FORM_INSPECTION:
            cdp.command(
                "Page.addScriptToEvaluateOnNewDocument",
                {
                    "source": """(() => {
                      if (window.__moneyStorageFetchCaptureInstalled) return;
                      window.__moneyStorageFetchCaptureInstalled = true;
                      window.__moneyStorageOffersCaptures = [];
                      const rememberCapture = item => {
                        const captures = window.__moneyStorageOffersCaptures;
                        captures.push(item);
                        if (captures.length > 12) captures.shift();
                      };
                      const originalFetch = window.fetch;
                      window.fetch = function(...args) {
                        return originalFetch.apply(this, args).then(response => {
                          try {
                            const rawUrl = args[0] instanceof Request ? args[0].url : String(args[0]);
                            const url = new URL(rawUrl, location.href);
                            // Capture the provider endpoint response first, then let the Python
                            // reader validate the exact query string and HTTP status.
                            const expected = url.origin === "https://storage.money"
                              && url.pathname === "/public_deals/fetch";
                            if (expected) {
                              response.clone().text().then(text => {
                                if (text.length <= 1000000) {
                                  rememberCapture({
                                    status: response.status,
                                    requestUrl: url.href,
                                    finalUrl: response.url,
                                    contentType: response.headers.get("content-type") || "",
                                    text
                                  });
                                } else {
                                  rememberCapture({ tooLarge: true, requestUrl: url.href, finalUrl: response.url });
                                }
                              }).catch(() => {});
                            }
                          } catch (_) {}
                          return response;
                        });
                      };
                      // Some page bundles use XMLHttpRequest rather than fetch.
                      // Observe its completed response too, without changing the request.
                      const xhrOpen = XMLHttpRequest.prototype.open;
                      const xhrSend = XMLHttpRequest.prototype.send;
                      XMLHttpRequest.prototype.open = function(method, url, ...rest) {
                        this.__moneyStorageRequestUrl = new URL(String(url), location.href).href;
                        return xhrOpen.call(this, method, url, ...rest);
                      };
                      XMLHttpRequest.prototype.send = function(...args) {
                        this.addEventListener("load", function() {
                          try {
                            const url = new URL(this.responseURL || this.__moneyStorageRequestUrl, location.href);
                            const expected = url.origin === "https://storage.money"
                              && url.pathname === "/public_deals/fetch";
                            if (!expected) return;
                            let text = "";
                            if (this.responseType === "" || this.responseType === "text") {
                              text = this.responseText;
                            } else if (this.responseType === "json") {
                              text = JSON.stringify(this.response);
                            } else {
                              return;
                            }
                            if (typeof text !== "string") return;
                            if (text.length > 1000000) {
                              rememberCapture({
                                tooLarge: true,
                                requestUrl: this.__moneyStorageRequestUrl,
                                finalUrl: this.responseURL || this.__moneyStorageRequestUrl
                              });
                              return;
                            }
                            rememberCapture({
                              status: this.status,
                              requestUrl: this.__moneyStorageRequestUrl,
                              finalUrl: this.responseURL || this.__moneyStorageRequestUrl,
                              contentType: this.getResponseHeader("content-type") || "",
                              text
                            });
                          } catch (_) {}
                        }, { once: true });
                        return xhrSend.apply(this, args);
                      };
                    })();"""
                },
            )
        # Reload once after Network.enable so the main-document HTTP status is
        # observable even when the initial navigation happened before CDP attach.
        cdp.command("Page.reload", {"ignoreCache": True})
        time.sleep(2)
        page = CDPPage(cdp)

        current_url, title, _ = page_state(cdp)
        print(f"BROWSER_READY=standalone Chromium; page={safe_location(current_url)}", flush=True)
        print(f"INITIAL_PAGE_TITLE={title[:100]!r}", flush=True)

        deadline = time.monotonic() + DEADLINE_SECONDS
        saw_eid = False
        eid_state_logged = False
        cloudflare_state: bool | None = None
        login_fallback_attempted = False
        login_route_attempted = False
        eid_login_action_attempted = False
        eid_login_link_probe_count = 0
        last_eid_login_link_probe = 0.0
        post_eid_navigation_attempted = False
        money_storage_form_diag_printed = False
        last_diag = 0.0

        while time.monotonic() < deadline:
            now = time.monotonic()
            current_url, title, body = page_state(cdp)
            parsed = urlparse(current_url)
            host = (parsed.hostname or "").lower()
            saw_eid = saw_eid or cdp.saw_eid_navigation
            storage_page = classify_money_storage_page(current_url)

            # Return-only diagnostics stop at the navigation milestone.
            # Normal mode must continue to the protected Deals page and read the
            # page-originated offers response before declaring authentication.
            if RETURN_ONLY and not SESSION_CHECK and not FORM_INSPECTION and has_returned_to_money_storage(current_url, eid_handoff_seen=saw_eid):
                document_status = (
                    cdp.storage_document_status
                    if cdp.storage_document_path == parsed.path else None
                )
                returned_marker = Path(os.environ["GITHUB_WORKSPACE"]) / "money-storage-returned.txt"
                returned_marker.write_text("returned_to_storage_money\n", encoding="utf-8")
                profile_ready = Path(os.environ["GITHUB_WORKSPACE"]) / "money-storage-profile-ready.txt"
                profile_ready.write_text("profile_ready\n", encoding="utf-8")
                STATUS_FILE.write_text("MONEY_STORAGE_RETURNED", encoding="utf-8")
                print(
                    "MONEY_STORAGE_RETURNED url=%s status=%s"
                    % (safe_location(current_url), document_status if document_status is not None else "not-observed"),
                    flush=True,
                )
                with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
                    summary.write("\\n## Money Storage E-ID return check\\n")
                    summary.write("- Browser returned from E-ID to an HTTPS page on storage.money.\\n")
                    summary.write("- No account endpoint, protected API, or offers page was required.\\n")
                    summary.write("- This confirms navigation only, not authenticated session validity.\\n")
                return 0

            challenge = classify_cloudflare_challenge(
                host=host,
                path=parsed.path,
                body=body,
                response_challenge=cdp.current_document_cf_challenge,
            )

            # Cloudflare is an independent access gate, not an E-ID state.
            # The user may encounter it before E-ID, after E-ID, both times,
            # or not at all. Never navigate away while its challenge is active.
            if challenge:
                if cloudflare_state is not True:
                    print("CLOUDFLARE_STATE=CHALLENGE_REQUIRED; waiting for the normal browser check", flush=True)
                cloudflare_state = True
                if SESSION_CHECK or NONINTERACTIVE:
                    STATUS_FILE.write_text("AUTH_REQUIRED", encoding="utf-8")
                    print("AUTH_REQUIRED: restored profile requires an interactive Cloudflare check", flush=True)
                    return 2
                time.sleep(2)
                continue
            if cloudflare_state is True:
                print("CLOUDFLARE_STATE=CHALLENGE_CLEARED", flush=True)
            cloudflare_state = False

            if host == "e-id.cards" or host.endswith(".e-id.cards"):
                saw_eid = True
                if not eid_state_logged:
                    print("EID_STATE=AUTHENTICATION_REQUIRED; waiting for user sign-in", flush=True)
                    eid_state_logged = True
                if SESSION_CHECK or NONINTERACTIVE:
                    STATUS_FILE.write_text("AUTH_REQUIRED", encoding="utf-8")
                    print("AUTH_REQUIRED: restored profile was redirected to E-ID; interactive sign-in is not available in this run", flush=True)
                    return 2

            # Follow only a visible E-ID link whose resolved HTTPS destination
            # is the official e-id.cards host. Identity verification remains
            # inside the provider's own browser flow.
            if (
                host == "storage.money"
                and storage_page == "login"
                and not SESSION_CHECK
                and not NONINTERACTIVE
                and not RETURN_ONLY
                and not FORM_INSPECTION
            ):
                if (
                    not eid_login_action_attempted
                    and eid_login_link_probe_count < 12
                    and now - last_eid_login_link_probe >= 5
                ):
                    last_eid_login_link_probe = now
                    eid_login_link_probe_count += 1
                    handoff = click_official_eid_action(cdp)
                    if handoff.get("clicked"):
                        eid_login_action_attempted = True
                        print(
                            "EID_HANDOFF=OFFICIAL_LOGIN_ACTION_OPENED host=%s path=%s"
                            % (handoff.get("host", "e-id.cards"), handoff.get("path", "/")),
                            flush=True,
                        )
                    elif eid_login_link_probe_count in (1, 12):
                        print(
                            "EID_HANDOFF=OFFICIAL_LOGIN_LINK_NOT_FOUND probe=%s/12; waiting on provider login page"
                            % eid_login_link_probe_count,
                            flush=True,
                        )
                time.sleep(2)
                continue

            # A provider route or URL alone never proves authentication. Reject
            # explicit HTTP/session-timeout evidence before attempting route handoff.
            document_status = (
                cdp.storage_document_status
                if cdp.storage_document_path == parsed.path else None
            )
            if host == "storage.money" and is_money_storage_auth_failure(
                status=document_status, title=title, body=body
            ):
                print(
                    "MONEY_STORAGE_AUTH_REQUIRED=YES status=%s path=%s; waiting for normal sign-in"
                    % (document_status if document_status is not None else "page-marker", parsed.path),
                    flush=True,
                )
                if SESSION_CHECK or NONINTERACTIVE:
                    STATUS_FILE.write_text("AUTH_REQUIRED", encoding="utf-8")
                    print("AUTH_REQUIRED: restored profile is not authenticated", flush=True)
                    return 2
                # Move to the provider's official login page once. The next
                # loop may open its visible E-ID link; it never fabricates an
                # OAuth URL or interacts with identity verification itself.
                if storage_page in ("deals", "account") and not login_route_attempted:
                    login_route_attempted = True
                    print("AUTH_HANDOFF=OPENING_PROVIDER_LOGIN_ROUTE", flush=True)
                    cdp.command("Page.navigate", {"url": "https://storage.money/login"})
                    time.sleep(2)
                    continue
                time.sleep(2)
                continue

            # /account is a valid post-E-ID landing page only when it is not
            # rejected and does not display an expired-session marker.
            if (SESSION_CHECK or NONINTERACTIVE) and storage_page == "login":
                STATUS_FILE.write_text("AUTH_REQUIRED", encoding="utf-8")
                print("AUTH_REQUIRED: restored profile reached a provider login route", flush=True)
                return 2

            # The E-ID callback commonly lands on /account. Once that normal
            # callback page has loaded without an auth-failure marker, return to
            # the offers tab so its own frontend can issue the authenticated
            # public_deals/fetch request captured by the normal reader.
            if (
                not SESSION_CHECK
                and not NONINTERACTIVE
                and not RETURN_ONLY
                and not FORM_INSPECTION
                and saw_eid
                and host == "storage.money"
                and storage_page == "account"
                and not post_eid_navigation_attempted
            ):
                post_eid_navigation_attempted = True
                print("EID_RETURN=ACCOUNT_CONFIRMED; opening the Everyone Offers tab", flush=True)
                # Persist the browser profile as soon as the provider's normal
                # E-ID callback returns to its own account domain. Do not make
                # profile persistence depend on the offers endpoint/parser:
                # quote inspection may fail independently of a valid login.
                profile_ready = Path(os.environ["GITHUB_WORKSPACE"]) / "money-storage-profile-ready.txt"
                profile_ready.write_text("profile_ready\\n", encoding="utf-8")
                print("CHROMIUM_PROFILE_PERSISTENCE=ELIGIBLE_AFTER_EID_RETURN", flush=True)
                cdp.command("Page.navigate", {"url": "https://storage.money/deals#tab-3"})
                time.sleep(2)
                continue

            if FORM_INSPECTION and host == "storage.money" and storage_page == "deals":
                document_status = (
                    cdp.storage_document_status
                    if cdp.storage_document_path == parsed.path else None
                )
                if is_money_storage_authenticated_offers_page(
                    current_url, status=document_status, title=title, body=body
                ):
                    if STATUS_FILE.read_text(encoding="utf-8") != "FORM_INSPECTION_READY":
                        deals_form_diagnostics(cdp)
                        STATUS_FILE.write_text("FORM_INSPECTION_READY", encoding="utf-8")
                        print("FORM_INSPECTION_READY: use the visible browser to select USDT → ECR", flush=True)
                    time.sleep(1)
                    continue

            if RETURN_ONLY and host == "storage.money" and storage_page == "deals":
                document_status = (
                    cdp.storage_document_status
                    if cdp.storage_document_path == parsed.path else None
                )
                if is_money_storage_authenticated_offers_page(
                    current_url, status=document_status, title=title, body=body
                ):
                    deals_form_diagnostics(cdp)
                    STATUS_FILE.write_text("MONEY_STORAGE_SESSION_CANDIDATE", encoding="utf-8")
                    profile_ready = Path(os.environ["GITHUB_WORKSPACE"]) / "money-storage-profile-ready.txt"
                    profile_ready.write_text("profile_ready\n", encoding="utf-8")
                    print(
                        "MONEY_STORAGE_SESSION_CANDIDATE route=storage.money/deals document_http=200",
                        flush=True,
                    )
                    with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
                        summary.write("\n## Money Storage existing-session candidate\n")
                        summary.write("- The current browser can open the protected /deals document.\n")
                        summary.write("- The encrypted profile will be saved for independent restoration verification.\n")
                        summary.write("- This is not yet the restored-session verification result.\n")
                        summary.write("- No offers API or quote values were read.\n")
                    return 0

            if SESSION_CHECK and host == "storage.money" and storage_page == "deals":
                document_status = (
                    cdp.storage_document_status
                    if cdp.storage_document_path == parsed.path else None
                )
                if is_money_storage_authenticated_offers_page(
                    current_url, status=document_status, title=title, body=body
                ):
                    STATUS_FILE.write_text("SESSION_AUTHENTICATED", encoding="utf-8")
                    print(
                        "SESSION_AUTHENTICATED route=storage.money/deals document_http=200",
                        flush=True,
                    )
                    with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
                        summary.write("\\n## Money Storage restored-session check\\n")
                        summary.write("- The encrypted profile was restored in a fresh Chromium process.\\n")
                        summary.write("- The protected /deals document returned HTTP 200 without a login/session-expired marker.\\n")
                        summary.write("- No offers API, quote values, or freshness data were read.\\n")
                    return 0

            if now - last_diag >= 20:
                last_diag = now
                challenge = any(
                    marker in body
                    for marker in (
                        "turnstile",
                        "cf-turnstile",
                        "checking your browser",
                        "verify you are human",
                        "captcha",
                        "robot",
                    )
                )
                denied = "access denied" in body or "доступ запрещ" in body
                print(
                    "AUTH_PROGRESS host=%s path=%s title=%r challenge_markers=%s access_denied_markers=%s"
                    % (parsed.netloc, parsed.path, title[:100], challenge, denied),
                    flush=True,
                )
                if challenge:
                    print("BOT_OR_ACCESS_CHALLENGE_SUSPECTED=YES", flush=True)
                if denied:
                    print("ACCESS_DENIED_PAGE_SUSPECTED=YES", flush=True)

            if (
                parsed.scheme == "https"
                and host == "storage.money"
                and parsed.path.rstrip("/") == "/deals"
                and cdp.storage_document_path == parsed.path
                and cdp.storage_document_status in (401, 403)
                and not login_fallback_attempted
            ):
                login_fallback_attempted = True
                print(
                    "MONEY_STORAGE_LOGIN_REQUIRED document_http=%s; opening the provider's normal account route"
                    % cdp.storage_document_status,
                    flush=True,
                )
                if SESSION_CHECK or NONINTERACTIVE:
                    STATUS_FILE.write_text("AUTH_REQUIRED", encoding="utf-8")
                    print("AUTH_REQUIRED: Money Storage rejected the restored session", flush=True)
                    return 2
                cdp.command("Page.navigate", {"url": "https://storage.money/account"})
                time.sleep(2)
                continue

            # Access-only phases must never fall through to the legacy quote reader.
            # A page that fails the access predicate is a failed/unknown check, not
            # permission to read the offers API.
            if RETURN_ONLY or SESSION_CHECK or FORM_INSPECTION:
                time.sleep(2)
                continue

            if storage_page == "deals":
                if NONINTERACTIVE and not money_storage_form_diag_printed:
                    deals_form_diagnostics(cdp)
                    money_storage_form_diag_printed = True
                try:
                    snapshot = None
                    for attempt in range(1, 4):
                        try:
                            snapshot = fetch_from_authenticated_page(page)
                            Path(os.environ["GITHUB_WORKSPACE"], "money-storage-profile-ready.txt").write_text(
                                "profile_ready\n", encoding="utf-8"
                            )
                            break
                        except TransientMoneyStorageReadError as exc:
                            print(
                                "OFFERS_READ_TRANSIENT_FAILURE attempt=%s/3 reason=%s"
                                % (attempt, str(exc)[:180]),
                                flush=True,
                            )
                            if attempt == 3:
                                raise
                            time.sleep(3 * attempt)
                        except RuntimeError as exc:
                            message = str(exc)
                            if any(marker in message for marker in (
                                "HTTP 401", "HTTP 403", "redirected outside the approved origin",
                                "response was not JSON",
                            )):
                                if SESSION_CHECK or NONINTERACTIVE:
                                    STATUS_FILE.write_text("AUTH_REQUIRED", encoding="utf-8")
                                    print("AUTH_REQUIRED: protected offers endpoint rejected the restored session", flush=True)
                                    return 2
                                print("MONEY_STORAGE_AUTH_REQUIRED=YES; waiting for normal E-ID flow", flush=True)
                                snapshot = None
                                break
                            raise
                    if snapshot is None:
                        time.sleep(2)
                        continue
                    output = Path(os.environ["GITHUB_WORKSPACE"]) / "money-storage-current-offers.json"
                    write_normalized_snapshot(snapshot, str(output))
                    Path(os.environ["GITHUB_WORKSPACE"], "session-authenticated.txt").write_text(
                        "money_storage\\n", encoding="utf-8"
                    )
                    with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
                        summary.write("\\n## Money Storage: «Всем предлагают»\\n")
                        summary.write("- Успешно прочитан актуальный снимок из восстановленной или вручную подтверждённой Chromium-сессии.\\n")
                        summary.write(f"- Предложений: {snapshot['offer_count']}\\n")
                        summary.write(f"- Средний курс USDT → ECR: {snapshot['rate']} ECR за 1 USDT\\n")
                        summary.write(f"- Время UTC: {snapshot['observed_at']}\\n")
                        summary.write("- Комиссия не учитывалась; история не сохранялась.\\n")
                    # Only the protected endpoint response plus validated payload
                    # establishes a successful read. The URL is not an auth signal.
                    print(
                        "AUTH_RETURN_ROUTE=%s"
                        % ("DIRECT_DEALS" if saw_eid else "SESSION_REUSED"),
                        flush=True,
                    )
                    print(
                        "MONEY_STORAGE_SESSION=AUTHENTICATED_AFTER_PROTECTED_READ",
                        flush=True,
                    )
                    STATUS_FILE.write_text("OFFERS_READ_OK", encoding="utf-8")
                    print(
                        "OFFERS_READ_OK count=%s rate=%s"
                        % (snapshot["offer_count"], snapshot["rate"]),
                        flush=True,
                    )
                    return 0
                except Exception as exc:
                    # The reader writes this marker only after the protected
                    # offers endpoint returned HTTP 200 with result=ok. Preserve
                    # that authenticated profile even if quote freshness fails.
                    authenticated_marker = Path(os.environ["GITHUB_WORKSPACE"]) / "session-authenticated.txt"
                    if authenticated_marker.is_file():
                        Path(os.environ["GITHUB_WORKSPACE"], "money-storage-profile-ready.txt").write_text(
                            "profile_ready\n", encoding="utf-8"
                        )
                    STATUS_FILE.write_text("OFFERS_READ_FAILED", encoding="utf-8")
                    print(
                        "OFFERS_READ_FAILED=%s reason=%s"
                        % (type(exc).__name__, str(exc)[:240]),
                        flush=True,
                    )
                    return 1

            time.sleep(2)

        final_status = "SESSION_CHECK_TIMEOUT" if SESSION_CHECK else ("AUTH_REQUIRED" if NONINTERACTIVE else "MONEY_STORAGE_RETURN_TIMEOUT")
        STATUS_FILE.write_text(final_status, encoding="utf-8")
        print(f"{final_status}: Chromium did not return from E-ID to storage.money", flush=True)
        return 1
    finally:
        cdp.close()


if __name__ == "__main__":
    raise SystemExit(main())
