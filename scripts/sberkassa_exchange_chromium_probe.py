"""Human-operated, read-only inspection of Sberkassa /exchange.

The probe never clicks, submits, changes form values, or sends non-GET
requests. It records only sanitized visible form state, quote/time fields,
and same-origin response metadata. E-ID/CAPTCHA/MFA remain manual.
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
    r"from|to|from_currency|to_currency|currency|currency_id|from_id|to_id|"
    r"base_currency|quote_currency|pair|pair_id|direction|updated_at|updatedAt|"
    r"timestamp|date|time|last_updated|refresh_time|created_at)$", re.I
)
CURRENCY = re.compile(r"^(RUB|RUR|USDT|USD|₽|руб\.?|тезер)$", re.I)
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

        samples = []
        last_signature = None
        last_capture = 0.0
        capture_deadline = time.monotonic() + 300
        while time.monotonic() < capture_deadline:
            state = probe.command("Runtime.evaluate", {
                "expression": """(() => {
                  const clean = v => String(v || '').trim().replace(/\\s+/g,' ').slice(0,180);
                  const visible = el => !!(el && el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden' && getComputedStyle(el).display !== 'none');
                  const body = document.body ? document.body.innerText : '';
                  const selects = Array.from(document.querySelectorAll('select')).filter(visible).slice(0,20).map(el => ({
                    label: clean(el.labels && Array.from(el.labels).map(x=>x.innerText).join(' ')),
                    name: clean(el.name), id: clean(el.id),
                    selected: clean(el.selectedOptions && el.selectedOptions[0] && el.selectedOptions[0].textContent),
                    value: clean(el.value)
                  }));
                  const inputs = Array.from(document.querySelectorAll('input')).filter(visible).slice(0,30).map(el => ({
                    type: clean(el.type), name: clean(el.name), id: clean(el.id),
                    placeholder: clean(el.placeholder), value: clean(el.value)
                  })).filter(x => /rate|курс|currency|from|to|price/i.test([x.name,x.id,x.placeholder].join(' ')))
                    .filter(x => /^(?:[-+]?\\d+(?:[.,]\\d+)?|RUB|RUR|USDT|USD)$/i.test(x.value));
                  const lines = body.split(/\\n/).map(x=>x.trim()).filter(x=>x && x.length<=180 && /(курс|rate|обновл|updated|refresh|last update)/i.test(x)).slice(0,40);
                  const timeLines = body.split(/\\n/).map(x=>x.trim()).filter(x=>x && /(обновл|updated|refresh|последн.*курс|last update)/i.test(x)).slice(0,15);
                  return {url:location.href,title:document.title,lines,time_lines:timeLines,selects,inputs};
                })()""",
                "returnByValue": True,
            }).get("result", {}).get("value", {})
            if urlparse(state.get("url", "")).path.rstrip("/") == "/exchange":
                probe.current_path = "/exchange"
                probe.drain_bodies()
                signature = json.dumps(state, sort_keys=True, ensure_ascii=False)
                if signature != last_signature:
                    samples.append({"observed_at_utc": datetime.now(timezone.utc).isoformat(),
                                    "dom": state})
                    samples = samples[-12:]
                    last_signature = signature
                    print("SBERKASSA_EXCHANGE_DOM_SAMPLE=UPDATED", flush=True)
                if time.monotonic() - last_capture >= 15:
                    last_capture = time.monotonic()
                    print("SBERKASSA_EXCHANGE_PROGRESS samples=%s responses=%s" %
                          (len(samples), len(probe.responses)), flush=True)
            time.sleep(3)

        artifact = {
            "schema_version": 1,
            "source": "sberkassa.site",
            "page": "/exchange",
            "read_only": True,
            "http_methods_allowed": ["GET"],
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "dom_samples": samples,
            "responses": probe.responses,
            "blocked_non_get_request_count": len(probe.blocked_methods),
            "limitations": [
                "No page controls were clicked or changed by the probe",
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
