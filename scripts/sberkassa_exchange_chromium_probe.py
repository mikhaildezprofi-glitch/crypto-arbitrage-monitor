"""Read-only inspection of Sberkassa /exchange with automatic currency selection.

The probe selects only RUB and USDT currency dropdowns, verifies the resulting
pair and displayed rate, and never enters an amount or clicks exchange/submit
controls. Non-GET requests are blocked. E-ID/CAPTCHA/MFA remain manual.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import websocket

DEBUG_ENDPOINT = "http://127.0.0.1:9222/json/list"
TARGET_URL = "https://sberkassa.site/exchange"
STATUS_FILE = Path("/tmp/eid-auth-status")
MAX_BODY_BYTES = 1_000_000
SAFE_KEYS = re.compile(
    r"^(rate|back_rate|exchange_rate|buy_rate|sell_rate|rate_value|price|"
    r"from|to|from_currency|to_currency|currency|currency_id|currency_code|currency_name|"
    r"code|symbol|name|from_id|to_id|base_currency|quote_currency|pair|pair_id|"
    r"direction|updated_at|updatedAt|timestamp|date|time|last_updated|refresh_time|created_at)$", re.I
)
CURRENCY = re.compile(r"^(RUB|RUR|USDT|USD|ERUB|E-RUBLE|₽|руб\.?|тезер|TETHER)$", re.I)
TIME_VALUE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", re.I)


def safe_location(value: str) -> str:
    parsed = urlparse(value)
    return f"{parsed.netloc}{parsed.path}"


def page_targets() -> list[dict]:
    request = urllib.request.Request(DEBUG_ENDPOINT, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=3) as response:
        items = json.loads(response.read().decode("utf-8"))
    return [x for x in items if x.get("type") == "page" and x.get("webSocketDebuggerUrl")]


def safe_scalar(key: str, value: object) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, (int, float)):
        return True
    if not isinstance(value, str):
        return False
    value = value.strip()
    return bool(
        re.fullmatch(r"[-+]?\d+(?:[.,]\d+)?", value)
        or TIME_VALUE.match(value)
        or CURRENCY.fullmatch(value)
    )


def safe_fields(payload: object, limit: int = 160) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []

    def walk(node: object, depth: int = 0) -> None:
        if depth > 8 or len(found) >= limit:
            return
        if isinstance(node, dict):
            for key, value in node.items():
                name = str(key)
                if SAFE_KEYS.fullmatch(name) and safe_scalar(name, value):
                    found.append({"key": name[:64], "value": str(value)[:80]})
                elif isinstance(value, (dict, list)):
                    walk(value, depth + 1)
        elif isinstance(node, list):
            for child in node[:80]:
                walk(child, depth + 1)

    walk(payload)
    return found


class Probe:
    def __init__(self, ws_url: str):
        self.ws = websocket.create_connection(
            ws_url, timeout=2, suppress_origin=True, enable_multithread=True
        )
        self.next_id = 0
        self.pending: list[tuple[str, str, int]] = []
        self.pending_scripts: list[tuple[str, str]] = []
        self.responses: list[dict] = []
        self.blocked_methods: list[str] = []
        self.current_path = ""

    def close(self) -> None:
        self.ws.close()

    def event(self, message: dict) -> None:
        method = message.get("method", "")
        params = message.get("params", {})
        if method == "Page.frameNavigated":
            frame = params.get("frame", {})
            if not frame.get("parentId"):
                self.current_path = urlparse(frame.get("url", "")).path
                print("NAV=" + self.current_path, flush=True)
        elif method == "Fetch.requestPaused":
            request = params.get("request", {})
            parsed = urlparse(request.get("url", ""))
            verb = str(request.get("method", "GET")).upper()
            allowed = parsed.hostname == "sberkassa.site" and verb == "GET"
            self.next_id += 1
            if allowed:
                command = {"id": self.next_id, "method": "Fetch.continueRequest",
                           "params": {"requestId": params["requestId"]}}
            else:
                self.blocked_methods.append(verb)
                command = {"id": self.next_id, "method": "Fetch.failRequest",
                           "params": {"requestId": params["requestId"],
                                      "errorReason": "BlockedByClient"}}
            self.ws.send(json.dumps(command))
        elif method == "Network.responseReceived":
            response = params.get("response", {})
            parsed = urlparse(response.get("url", ""))
            if parsed.hostname != "sberkassa.site":
                return
            resource_type = params.get("type", "unknown")
            status = int(response.get("status", 0))
            headers = response.get("headers", {})
            allowed_headers = {"date", "last-modified", "expires", "age",
                               "cache-control", "etag", "content-type"}
            safe_headers = {
                str(k).lower(): str(v)[:180]
                for k, v in headers.items()
                if str(k).lower() in allowed_headers and len(str(v)) <= 180
            }
            item = {
                "path": parsed.path[:160],
                "resource_type": resource_type,
                "status": status,
                "mime_type": str(response.get("mimeType", ""))[:80],
                "from_disk_cache": bool(response.get("fromDiskCache", False)),
                "from_service_worker": bool(response.get("fromServiceWorker", False)),
                "response_time_epoch_ms": response.get("responseTime"),
                "request_time_monotonic_seconds": response.get("timing", {}).get("requestTime"),
                "encoded_data_length": response.get("encodedDataLength"),
                "headers": safe_headers,
                "quote_fields": [],
            }
            if len(self.responses) < 100:
                self.responses.append(item)
            if resource_type in ("XHR", "Fetch") and "json" in str(response.get("mimeType", "")).lower():
                self.pending.append((params.get("requestId", ""), parsed.path, status))
            elif resource_type == "Script" and parsed.path.startswith("/js/") and status == 200:
                self.pending_scripts.append((params.get("requestId", ""), parsed.path))

    def command(self, method: str, params: dict | None = None, timeout: float = 8) -> dict:
        self.next_id += 1
        command_id = self.next_id
        self.ws.send(json.dumps({"id": command_id, "method": method, "params": params or {}}))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                message = json.loads(self.ws.recv())
            except websocket.WebSocketTimeoutException:
                continue
            if "method" in message:
                self.event(message)
            if message.get("id") == command_id:
                if "error" in message:
                    raise RuntimeError("CDP command failed: " + method)
                return message.get("result", {})
        raise TimeoutError("CDP command timed out: " + method)

    def drain_bodies(self) -> None:
        pending, self.pending = self.pending, []
        for request_id, path, status in pending[:20]:
            if not request_id:
                continue
            try:
                body = self.command("Network.getResponseBody", {"requestId": request_id}, timeout=3)
                raw = body.get("body", "").encode("utf-8")
                if body.get("base64Encoded"):
                    import base64
                    raw = base64.b64decode(body["body"], validate=True)
                if len(raw) > MAX_BODY_BYTES:
                    continue
                payload = json.loads(raw.decode("utf-8"))
                fields = safe_fields(payload)
                for item in self.responses:
                    if item["path"] == path and item["status"] == status and not item["quote_fields"]:
                        item["quote_fields"] = fields
                        break
                print("EXCHANGE_JSON path=%s status=%s safe_fields=%s" %
                      (path, status, json.dumps(fields[:30], ensure_ascii=False)), flush=True)
            except Exception as exc:
                print("EXCHANGE_JSON_UNAVAILABLE path=%s reason=%s" %
                      (path, type(exc).__name__), flush=True)

        pending_scripts, self.pending_scripts = self.pending_scripts, []
        for request_id, path in pending_scripts[:20]:
            if not request_id:
                continue
            try:
                body = self.command("Network.getResponseBody", {"requestId": request_id}, timeout=3)
                raw = body.get("body", "").encode("utf-8")
                if body.get("base64Encoded"):
                    import base64
                    raw = base64.b64decode(body["body"], validate=True)
                if len(raw) > MAX_BODY_BYTES:
                    continue
                source = raw.decode("utf-8", errors="replace")
                endpoints = sorted(set(re.findall(
                    r"""['"]((?:/api/|/public_deals/)[^'"\\s]{1,140})['"]""", source
                )))
                endpoints = [x for x in endpoints if not re.search(
                    r"(create|order|deposit|withdraw|transfer|payment|submit)", x, re.I
                )][:40]
                selectors = sorted(set(re.findall(
                    r"""['"]([.#][A-Za-z0-9_-]*(?:currency|rate|convert|exchange)[A-Za-z0-9_-]*)['"]""",
                    source, re.I
                )))[:60]
                fields = sorted(set(re.findall(
                    r"""['"]([A-Za-z_][A-Za-z0-9_]{0,60})['"]""", source
                )))
                fields = [x for x in fields if re.search(
                    r"(currency|rate|price|exchange|convert|updated|refresh)|(^|_)(from|to)(_|$)", x, re.I
                ) and not re.search(r"(top_up|deal_create|order|deposit|withdraw|transfer)", x, re.I)][:80]
                methods = sorted(set(re.findall(
                    r"""(?:method|type)\\s*:\\s*['"](GET|POST|PUT|DELETE)['"]""",
                    source, re.I
                )))
                hints = {"path": path, "api_paths": endpoints, "selectors": selectors,
                         "field_names": fields, "declared_http_methods": methods}
                for item in self.responses:
                    if item["path"] == path and item["resource_type"] == "Script":
                        item["script_hints"] = hints
                        break
                print("EXCHANGE_SCRIPT_HINTS path=%s api_paths=%s selectors=%s fields=%s methods=%s" %
                      (path, json.dumps(endpoints), json.dumps(selectors),
                       json.dumps(fields), json.dumps(methods)), flush=True)
            except Exception as exc:
                print("EXCHANGE_SCRIPT_HINTS_UNAVAILABLE path=%s reason=%s" %
                      (path, type(exc).__name__), flush=True)


def main() -> int:
    STATUS_FILE.write_text("SBERKASSA_EXCHANGE_WAITING_FOR_AUTH", encoding="utf-8")
    deadline = time.monotonic() + 120
    target = None
    while time.monotonic() < deadline:
        try:
            targets = page_targets()
            target = next((x for x in targets
                           if "sberkassa.site" in x.get("url", "")),
                          targets[0] if targets else None)
            if target:
                break
        except Exception:
            pass
        time.sleep(1)
    if not target:
        raise RuntimeError("No Chromium page target")
    probe = Probe(target["webSocketDebuggerUrl"])
    try:
        probe.command("Page.enable")
        probe.command("Runtime.enable")
        probe.command("Network.enable")
        probe.command("Network.setCacheDisabled", {"cacheDisabled": True})
        probe.command("Fetch.enable", {"patterns": [
            {"urlPattern": "https://sberkassa.site/*", "requestStage": "Request"}
        ]})
        probe.current_path = "/exchange"
        probe.command("Page.navigate", {"url": TARGET_URL})
        print("SBERKASSA_EXCHANGE_PROBE_READY=YES", flush=True)
        print("SBERKASSA_EXCHANGE_SCOPE=READ_ONLY_GET_ONLY", flush=True)

        eid_seen = False
        callback_returned = False
        authenticated = False
        auth_deadline = time.monotonic() + 1800
        while time.monotonic() < auth_deadline:
            state = probe.command("Runtime.evaluate", {
                "expression": """(() => ({url: location.href, body: document.body ? document.body.innerText.slice(0,10000) : ''}))()""",
                "returnByValue": True,
            }).get("result", {}).get("value", {})
            parsed = urlparse(state.get("url", ""))
            host = (parsed.hostname or "").lower()
            if host == "e-id.cards" or host.endswith(".e-id.cards"):
                eid_seen = True
                print("EID_HANDOFF=IDENTITY_PROVIDER_SEEN", flush=True)
            if host == "sberkassa.site" and parsed.path.rstrip("/") == "/exchange":
                probe.current_path = "/exchange"
                probe.drain_bodies()
                body = str(state.get("body", "")).lower()
                if len(body) > 20 and not any(x in body for x in ("войти", "авторизац", "sign in", "login")):
                    authenticated = True
                    break
            if eid_seen and host == "sberkassa.site" and not callback_returned:
                callback_returned = True
                print("EID_HANDOFF=SBERKASSA_CALLBACK_RETURNED", flush=True)
                probe.command("Page.navigate", {"url": TARGET_URL})
            time.sleep(2)

        if not authenticated:
            STATUS_FILE.write_text("SBERKASSA_EXCHANGE_AUTH_TIMEOUT", encoding="utf-8")
            print("SBERKASSA_EXCHANGE_AUTH_REQUIRED_OR_PAGE_UNAVAILABLE=YES", flush=True)
            return 1

        Path("session-authenticated.txt").write_text("sberkassa\n", encoding="utf-8")
        Path("money-storage-profile-ready.txt").write_text("profile_ready\n", encoding="utf-8")
        print("SBERKASSA_EXCHANGE_SESSION=AUTHENTICATED", flush=True)

        # Automatically select RUB -> USDT using only the two currency dropdowns.
        # The probe never enters an amount and never activates exchange/submit controls.
        selection_expression = """(() => {
          const codeFromLabel = value => {
            const text = String(value || '').toUpperCase();
            if (/\\bUSDT\\b|TETHER|ТЕЗЕР/.test(text)) return 'USDT';
            if (/\\bERUB\\b|E-RUBLE|Е-РУБЛ/.test(text)) return 'ERUB';
            if (/\\bRUB\\b|\\bRUR\\b|РОССИЙСКИЙ\\s+РУБЛЬ|РУБЛЬ|₽/.test(text)) return 'RUB';
            if (/\\bUSD\\b/.test(text)) return 'USD';
            return '';
          };
          const selectedLabel = dir => {
            const label = document.querySelector('#currency_' + dir + 'SelectBoxItText');
            const select = document.querySelector('#currency_' + dir);
            return (label && (label.innerText || label.textContent))
              || (select && select.selectedOptions && select.selectedOptions[0] && select.selectedOptions[0].textContent)
              || '';
          };
          const visible = el => !!(el && el.getClientRects().length
            && getComputedStyle(el).visibility !== 'hidden'
            && getComputedStyle(el).display !== 'none');
          const chooseByClick = (dir, wantedCode) => {
            if (codeFromLabel(selectedLabel(dir)) === wantedCode) {
              return {selected:true, action:'already_selected'};
            }
            const optionsRoot = document.querySelector('#currency_' + dir + 'SelectBoxItOptions');
            const optionNodes = optionsRoot
              ? Array.from(optionsRoot.querySelectorAll('li,a,[role="option"]'))
              : [];
            const option = optionNodes.find(el => codeFromLabel(el.innerText || el.textContent) === wantedCode);
            if (option && visible(option)) {
              option.click();
              return {selected:false, action:'clicked_option'};
            }
            const trigger = document.querySelector('#currency_' + dir + 'SelectBoxIt');
            if (trigger && visible(trigger)) {
              trigger.click();
              return {selected:false, action:'opened_dropdown'};
            }
            const nativeSelect = document.querySelector('#currency_' + dir);
            if (nativeSelect && nativeSelect.options && nativeSelect.options.length) {
              const nativeOption = Array.from(nativeSelect.options)
                .find(el => codeFromLabel(el.textContent || el.label || el.value) === wantedCode);
              if (nativeOption) {
                nativeSelect.value = nativeOption.value;
                nativeSelect.dispatchEvent(new Event('input', {bubbles:true}));
                nativeSelect.dispatchEvent(new Event('change', {bubbles:true}));
                return {selected:false, action:'selected_native_option'};
              }
            }
            return {selected:false, action:'dropdown_control_missing'};
          };
          const fromAction = chooseByClick('from', 'RUB');
          const toAction = chooseByClick('to', 'USDT');
          const fromLabel = String(selectedLabel('from') || '').trim().slice(0,120);
          const toLabel = String(selectedLabel('to') || '').trim().slice(0,120);
          return {
            url:location.href,
            selected_pair:{from:codeFromLabel(fromLabel),to:codeFromLabel(toLabel)},
            selected_labels:{from:fromLabel,to:toLabel},
            displayed_rate_text:String((document.querySelector('#current_rate')?.innerText || '').trim()).slice(0,180),
            selection_actions:{from:fromAction,to:toAction}
          };
        })()""";

        selection = {
            "manual_selection_required": False,
            "selection_method": "automatic_currency_dropdown_selection",
            "selected_pair": {},
            "selected_labels": {},
            "displayed_rate_text": "",
            "selection_confirmed": False,
            "sell_amount_entered": False,
            "exchange_submit_clicked": False,
        }
        samples = []
        print("SBERKASSA_EXCHANGE_AUTOMATIC_SELECTION=STARTED", flush=True)
        selection_deadline = time.monotonic() + 300
        while time.monotonic() < selection_deadline:
            state = probe.command("Runtime.evaluate", {
                "expression": selection_expression,
                "returnByValue": True,
            }).get("result", {}).get("value", {})
            if urlparse(state.get("url", "")).path.rstrip("/") == "/exchange":
                probe.current_path = "/exchange"
                probe.drain_bodies()
                pair = state.get("selected_pair", {})
                rate_text = str(state.get("displayed_rate_text", "")).strip()
                if pair.get("from") == "RUB" and pair.get("to") == "USDT" and rate_text:
                    observed_at = datetime.now(timezone.utc).isoformat()
                    selection.update({
                        "selected_pair": pair,
                        "selected_labels": state.get("selected_labels", {}),
                        "displayed_rate_text": rate_text,
                        "selection_confirmed": True,
                        "observed_at_utc": observed_at,
                        "selection_actions": state.get("selection_actions", {}),
                    })
                    samples.append({"observed_at_utc": observed_at, "dom": state})
                    print("SBERKASSA_EXCHANGE_AUTOMATIC_PAIR_CONFIRMED=RUB_USDT", flush=True)
                    break
            time.sleep(2)

        if selection.get("selection_confirmed") is not True:
            STATUS_FILE.write_text("SBERKASSA_EXCHANGE_SELECTION_TIMEOUT", encoding="utf-8")
            print("SBERKASSA_EXCHANGE_SELECTION_TIMEOUT=YES", flush=True)
            return 1
        print("SBERKASSA_EXCHANGE_UI_SELECTION=" + json.dumps(selection, ensure_ascii=False), flush=True)
        print("SBERKASSA_EXCHANGE_RESULT_RECEIVED=YES", flush=True)

        artifact = {
            "schema_version": 1,
            "source": "sberkassa.site",
            "page": "/exchange",
            "read_only": True,
            "http_methods_allowed": ["GET"],
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "ui_selection": selection,
            "latest_dom_selection": ({
                "selected_pair": samples[-1]["dom"].get("selected_pair", {}) if samples else {},
                "selected_labels": samples[-1]["dom"].get("selected_labels", {}) if samples else {},
                "displayed_rate_text": samples[-1]["dom"].get("displayed_rate_text", "") if samples else "",
                "observed_at_utc": samples[-1].get("observed_at_utc", "") if samples else "",
            }),
            "dom_samples": samples,
            "responses": probe.responses,
            "blocked_non_get_request_count": len(probe.blocked_methods),
            "limitations": [
                "The probe automatically selected RUB -> USDT using only the currency dropdowns; it did not enter amounts or click exchange/submit controls",
                "The final selected pair and displayed rate are read from the latest captured DOM snapshot, independently of click-attempt status",
                "All non-GET requests to sberkassa.site were blocked",
                "Only allowlisted numeric quote/time/currency fields and visible form state are retained",
                "HTTP cache headers and browser timing are diagnostics only, not proof of quote freshness",
                "No rate is considered validated until RUB->USDT direction and a successful refresh signal are independently established",
                "No raw response bodies, cookies, authorization headers, tokens, or personal form data are published"
            ]
        }
        Path("sberkassa-exchange-inspection.json").write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        with open(__import__("os").environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
            summary.write("\n## Sberkassa /exchange read-only inspection\n")
            summary.write("- Inspected /exchange using the restored authenticated Chromium profile or manual E-ID handoff.\n")
            summary.write("- The probe did not click or modify page controls and blocked all non-GET requests to Sberkassa.\n")
            summary.write("- Captured sanitized visible form state and allowlisted quote/time fields only.\n")
            summary.write("- No quote freshness or RUB -> USDT rate is asserted by this discovery run.\n")
        STATUS_FILE.write_text("SBERKASSA_EXCHANGE_INSPECTION_COMPLETE", encoding="utf-8")
        print("SBERKASSA_EXCHANGE_INSPECTION_COMPLETE=YES", flush=True)
        return 0
    finally:
        probe.close()


if __name__ == "__main__":
    raise SystemExit(main())
