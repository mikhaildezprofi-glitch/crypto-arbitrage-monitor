"""Human-operated, read-only CDP probe for Sberkassa quote pages.

The user completes E-ID and any ordinary verification manually in the visible
standalone Chromium window. This helper observes only sanitized request metadata,
page update-marker lines, and selected numeric quote-related JSON fields.

It never clicks, submits forms, solves challenges, exports cookies, reads
authorization headers, or prints raw response bodies.
"""
from __future__ import annotations

import base64
import json
import re
import time
import urllib.request
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import websocket

DEBUG_ENDPOINT = "http://127.0.0.1:9222/json/list"
STATUS_FILE = Path("/tmp/eid-auth-status")
DEADLINE_SECONDS = 1800
MAX_BODY_BYTES = 1_000_000
VALUE_KEYS = re.compile(
    r"(rate|price|amount|min|max|volume|reserve|commission|updated|timestamp|created|date|time)",
    re.I,
)
TIME_LINE = re.compile(r"(обновл|updated|refresh|время обнов|последн.*курс|last update)", re.I)


def safe_location(value: str) -> str:
    parsed = urlparse(value)
    suffix = f"#{parsed.fragment}" if parsed.fragment else ""
    return f"{parsed.netloc}{parsed.path}{suffix}"


def page_targets() -> list[dict]:
    request = urllib.request.Request(DEBUG_ENDPOINT, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=3) as response:
        targets = json.loads(response.read().decode("utf-8"))
    return [
        item for item in targets
        if item.get("type") == "page" and item.get("webSocketDebuggerUrl")
    ]


def scalar_is_safe(value: object, key: str) -> bool:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return False
    text = str(value).strip()
    if not text or len(text) > 48:
        return False
    if isinstance(value, (int, float)):
        return True
    if re.fullmatch(r"[-+]?\d+(?:[.,]\d+)?", text):
        return True
    return bool(re.search(r"(date|time|updated|timestamp|created)", key, re.I))


def extract_quote_fields(value: object) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []

    def walk(node: object, depth: int = 0) -> None:
        if depth > 8 or len(found) >= 80:
            return
        if isinstance(node, dict):
            for key, child in node.items():
                name = str(key)
                if VALUE_KEYS.search(name) and scalar_is_safe(child, name):
                    found.append((name[:64], str(child)[:48]))
                elif isinstance(child, (dict, list)):
                    walk(child, depth + 1)
        elif isinstance(node, list):
            for child in node[:50]:
                walk(child, depth + 1)

    walk(value)
    return found


class CDP:
    def __init__(self, ws_url: str):
        self.ws = websocket.create_connection(
            ws_url, timeout=2, suppress_origin=True, enable_multithread=True
        )
        self.next_id = 0
        self.pending_bodies: list[tuple[str, str]] = []

    def close(self) -> None:
        self.ws.close()

    def event(self, message: dict) -> None:
        method = message.get("method", "")
        params = message.get("params", {})
        if method == "Page.frameNavigated":
            frame = params.get("frame", {})
            if not frame.get("parentId"):
                print(f"NAV={safe_location(frame.get('url', ''))}", flush=True)
        elif method == "Network.requestWillBeSent":
            request = params.get("request", {})
            parsed = urlparse(request.get("url", ""))
            if parsed.hostname != "sberkassa.site":
                return
            query_keys = sorted(parse_qs(parsed.query, keep_blank_values=True).keys())
            print(
                "REQUEST host=sberkassa.site path=%s method=%s type=%s query_keys=%s"
                % (
                    parsed.path,
                    request.get("method", "GET"),
                    params.get("type", "unknown"),
                    ",".join(query_keys[:20]) or "none",
                ),
                flush=True,
            )
        elif method == "Network.responseReceived":
            response = params.get("response", {})
            parsed = urlparse(response.get("url", ""))
            host = (parsed.hostname or "").lower()
            if host != "sberkassa.site" and host != "e-id.cards" and "cloudflare" not in host:
                return
            mime = (response.get("mimeType") or "unknown").split(";")[0]
            status = int(response.get("status", 0))
            print(
                "HTTP_DIAG host=%s path=%s status=%s type=%s content_type=%s"
                % (host, parsed.path, status, params.get("type", "unknown"), mime),
                flush=True,
            )
            if host == "sberkassa.site" and params.get("type") in ("XHR", "Fetch") and "json" in mime:
                self.pending_bodies.append((params.get("requestId", ""), parsed.path))

    def command(self, method: str, params: dict | None = None, timeout: float = 8) -> dict:
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
                self.event(message)
            if message.get("id") == command_id:
                if "error" in message:
                    raise RuntimeError("CDP command failed: " + method)
                return message.get("result", {})
        raise TimeoutError("CDP command timed out: " + method)

    def drain_json_bodies(self) -> None:
        pending, self.pending_bodies = self.pending_bodies, []
        for request_id, path in pending[:20]:
            if not request_id:
                continue
            try:
                result = self.command("Network.getResponseBody", {"requestId": request_id}, timeout=3)
                body = result.get("body", "")
                if result.get("base64Encoded"):
                    raw = base64.b64decode(body, validate=True)
                else:
                    raw = body.encode("utf-8")
                if len(raw) > MAX_BODY_BYTES:
                    print(f"JSON_SCHEMA path={path} skipped=body_over_1mb", flush=True)
                    continue
                payload = json.loads(raw.decode("utf-8"))
                fields = extract_quote_fields(payload)
                counts = Counter(name for name, _ in fields)
                print(
                    "QUOTE_FIELDS path=%s fields=%s samples=%s"
                    % (
                        path,
                        ",".join(f"{key}:{count}" for key, count in sorted(counts.items())) or "none",
                        json.dumps(fields[:40], ensure_ascii=False, separators=(",", ":")),
                    ),
                    flush=True,
                )
            except Exception as exc:
                print(f"JSON_SCHEMA path={path} unavailable={type(exc).__name__}", flush=True)


def connect() -> CDP:
    deadline = time.monotonic() + 120
    last_error = "no page target"
    while time.monotonic() < deadline:
        try:
            targets = page_targets()
            target = next(
                (item for item in targets if "sberkassa.site" in item.get("url", "")),
                targets[0] if targets else None,
            )
            if target:
                return CDP(target["webSocketDebuggerUrl"])
        except Exception as exc:
            last_error = type(exc).__name__
        time.sleep(1)
    raise RuntimeError("Could not attach to standalone Chromium: " + last_error)


def main() -> int:
    STATUS_FILE.write_text("SBERKASSA_WAITING_FOR_LOGIN", encoding="utf-8")
    cdp = connect()
    try:
        cdp.command("Page.enable")
        cdp.command("Runtime.enable")
        cdp.command("Network.enable")
        print("SBERKASSA_PROBE_READY=YES", flush=True)

        seen_deals = False
        seen_exchange = False
        last_target_activity = 0.0
        last_progress = 0.0
        deadline = time.monotonic() + DEADLINE_SECONDS

        while time.monotonic() < deadline:
            state = cdp.command(
                "Runtime.evaluate",
                {
                    "expression": """(() => ({
                      url: location.href,
                      title: document.title || "",
                      updateLines: (document.body ? document.body.innerText : "")
                        .split(/\\n/)
                        .map(x => x.trim())
                        .filter(x => x && /(обновл|updated|refresh|время обнов|последн.*курс|last update)/i.test(x))
                        .slice(0, 8)
                    }))()""",
                    "returnByValue": True,
                },
            ).get("result", {}).get("value", {})
            url = state.get("url", "")
            parsed = urlparse(url)
            is_deals = (
                parsed.hostname == "sberkassa.site"
                and parsed.path.rstrip("/") == "/deals"
                and parsed.fragment == "tab-3"
            )
            is_exchange = (
                parsed.hostname == "sberkassa.site"
                and parsed.path.rstrip("/") == "/exchange"
            )

            if is_deals and not seen_deals:
                seen_deals = True
                last_target_activity = time.monotonic()
                print("SBERKASSA_DEALS_PAGE_SEEN=YES", flush=True)
            if is_exchange and not seen_exchange:
                seen_exchange = True
                last_target_activity = time.monotonic()
                print("SBERKASSA_EXCHANGE_PAGE_SEEN=YES", flush=True)

            if is_deals or is_exchange:
                page_name = "deals_everyone_offers" if is_deals else "exchange_rub_usdt"
                markers = state.get("updateLines", [])
                print(
                    "PAGE_UPDATE_MARKERS page=%s title=%r lines=%s"
                    % (page_name, state.get("title", "")[:100], json.dumps(markers, ensure_ascii=False)),
                    flush=True,
                )
                if time.monotonic() - last_target_activity > 2:
                    last_target_activity = time.monotonic()

            cdp.drain_json_bodies()

            now = time.monotonic()
            if now - last_progress >= 20:
                last_progress = now
                print(
                    "SBERKASSA_PROGRESS deals_seen=%s exchange_seen=%s location=%s"
                    % (seen_deals, seen_exchange, safe_location(url)),
                    flush=True,
                )

            if seen_deals and seen_exchange and now - last_target_activity >= 12:
                with open(Path(__import__("os").environ["GITHUB_STEP_SUMMARY"]), "a", encoding="utf-8") as summary:
                    summary.write("\n## Sberkassa read-only page inspection\n")
                    summary.write("- Both requested pages were visited in the manually authenticated standalone Chromium session.\n")
                    summary.write("- Captured sanitized request/response metadata, quote-related JSON field names and numeric samples, and visible update-marker lines.\n")
                    summary.write("- No raw response body, cookies, session tokens, or authorization headers were published.\n")
                    summary.write("- Page timestamps must still be checked against successful refresh behavior before enabling freshness checks.\n")
                STATUS_FILE.write_text("SBERKASSA_CAPTURE_COMPLETE", encoding="utf-8")
                print("SBERKASSA_CAPTURE_COMPLETE=YES", flush=True)
                return 0

            time.sleep(2)

        STATUS_FILE.write_text("SBERKASSA_CAPTURE_TIMEOUT", encoding="utf-8")
        print("SBERKASSA_CAPTURE_TIMEOUT=YES", flush=True)
        return 1
    except Exception as exc:
        STATUS_FILE.write_text("SBERKASSA_CAPTURE_FAILED", encoding="utf-8")
        print("SBERKASSA_CAPTURE_FAILED=%s" % type(exc).__name__, flush=True)
        return 1
    finally:
        cdp.close()


if __name__ == "__main__":
    raise SystemExit(main())
