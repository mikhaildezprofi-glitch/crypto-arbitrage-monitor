"""Human-operated Chromium session bridge for the Money Storage E-ID handoff.

Chromium is launched as a normal visible desktop application by the workflow.
This helper attaches to its local DevTools Protocol endpoint only to observe
navigation and, after the user completes E-ID, read the approved same-origin
Money Storage endpoint from that already-authenticated tab.

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
from urllib.parse import urlparse

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

DEBUG_ENDPOINT = "http://127.0.0.1:9222/json/list"
STATUS_FILE = Path("/tmp/eid-auth-status")
DEADLINE_SECONDS = 1800


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

    def close(self) -> None:
        self.ws.close()

    def _event(self, message: dict) -> None:
        method = message.get("method", "")
        params = message.get("params", {})

        if method == "Page.frameNavigated":
            frame = params.get("frame", {})
            if not frame.get("parentId"):
                self.main_frame_id = frame.get("id")
                location = safe_location(frame.get("url", ""))
                print(f"NAV={location}", flush=True)

        elif method == "Network.responseReceived":
            response = params.get("response", {})
            parsed = urlparse(response.get("url", ""))
            host = (parsed.hostname or "").lower()
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
                # Prefer the visible Money Storage tab if it is already present.
                target = next(
                    (item for item in targets if "storage.money" in item.get("url", "")),
                    targets[0],
                )
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


def main() -> int:
    STATUS_FILE.write_text("WAITING_FOR_LOGIN", encoding="utf-8")
    cdp = connect_to_chromium()
    try:
        cdp.command("Page.enable")
        cdp.command("Runtime.enable")
        cdp.command("Network.enable")
        # Capture the offers JSON from the page's own authenticated fetch. The
        # response is cloned asynchronously; the original response is untouched.
        cdp.command(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": """(() => {
                  if (window.__moneyStorageFetchCaptureInstalled) return;
                  window.__moneyStorageFetchCaptureInstalled = true;
                  const originalFetch = window.fetch;
                  window.fetch = function(...args) {
                    return originalFetch.apply(this, args).then(response => {
                      try {
                        const rawUrl = args[0] instanceof Request ? args[0].url : String(args[0]);
                        const url = new URL(rawUrl, location.href);
                        const expected = url.origin === "https://storage.money"
                          && url.pathname === "/public_deals/fetch"
                          && url.searchParams.get("offset") === "0"
                          && url.searchParams.get("limit") === "20"
                          && url.searchParams.get("from") === "ECR"
                          && url.searchParams.get("to") === "USDT";
                        if (expected && response.status === 200 && !window.__moneyStorageOffersCapture) {
                          response.clone().text().then(text => {
                            if (text.length <= 1000000) {
                              window.__moneyStorageOffersCapture = {
                                status: response.status,
                                finalUrl: response.url,
                                contentType: response.headers.get("content-type") || "",
                                text
                              };
                            }
                          }).catch(() => {});
                        }
                      } catch (_) {}
                      return response;
                    });
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
        login_fallback_attempted = False
        last_diag = 0.0

        while time.monotonic() < deadline:
            now = time.monotonic()
            current_url, title, body = page_state(cdp)
            parsed = urlparse(current_url)
            host = (parsed.hostname or "").lower()

            if host == "e-id.cards" or host.endswith(".e-id.cards"):
                saw_eid = True

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
                cdp.command("Page.navigate", {"url": "https://storage.money/account"})
                time.sleep(2)
                continue

            if (
                saw_eid
                and parsed.scheme == "https"
                and host == "storage.money"
                and parsed.path.rstrip("/") == "/account"
            ):
                print("AUTH_RETURNED_TO_ACCOUNT", flush=True)
                cdp.command("Page.navigate", {"url": "https://storage.money/deals#tab-3"})
                time.sleep(2)
                continue

            if (
                parsed.scheme == "https"
                and host == "storage.money"
                and parsed.path.rstrip("/") == "/deals"
                and parsed.fragment == "tab-3"
            ):
                print(
                    "MONEY_STORAGE_SESSION=%s"
                    % ("AUTHENTICATED_AFTER_EID" if saw_eid else "RESTORED_PROFILE_REUSED"),
                    flush=True,
                )
                try:
                    snapshot = None
                    for attempt in range(1, 4):
                        try:
                            snapshot = fetch_from_authenticated_page(page)
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
                    STATUS_FILE.write_text("OFFERS_READ_OK", encoding="utf-8")
                    print(
                        "OFFERS_READ_OK count=%s rate=%s"
                        % (snapshot["offer_count"], snapshot["rate"]),
                        flush=True,
                    )
                    return 0
                except Exception as exc:
                    STATUS_FILE.write_text("OFFERS_READ_FAILED", encoding="utf-8")
                    print(
                        "OFFERS_READ_FAILED=%s reason=%s"
                        % (type(exc).__name__, str(exc)[:240]),
                        flush=True,
                    )
                    return 1

            time.sleep(2)

        STATUS_FILE.write_text("AUTH_TIMEOUT", encoding="utf-8")
        print("AUTH_TIMEOUT: Chromium did not return to Money Storage account", flush=True)
        return 1
    finally:
        cdp.close()


if __name__ == "__main__":
    raise SystemExit(main())
