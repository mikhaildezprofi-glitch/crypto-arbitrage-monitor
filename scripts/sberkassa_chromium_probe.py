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
from datetime import datetime, timezone
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import websocket

sys.path.insert(0, str(Path.cwd()))
sys.path.insert(0, str(Path.cwd() / "src"))
from scripts.money_storage_cloud_read import parse_page_update_timestamp

DEBUG_ENDPOINT = "http://127.0.0.1:9222/json/list"
STATUS_FILE = Path("/tmp/eid-auth-status")
DEADLINE_SECONDS = 1800
MAX_BODY_BYTES = 1_000_000
VALUE_KEYS = re.compile(
    r"(rate|price|updated|timestamp|date|time)",
    re.I,
)
TIME_LINE = re.compile(r"(обновл|updated|refresh|время обнов|последн.*курс|last update)", re.I)
SAFE_OFFER_KEYS = re.compile(
    r"^(from|to|from_currency|to_currency|give_currency|receive_currency|"
    r"currency_from|currency_to|base_currency|quote_currency|source_currency|"
    r"target_currency|currency_id|from_id|to_id|give_id|receive_id|"
    r"currency1|currency2|currency1_id|currency2_id|currency_give|currency_receive|"
    r"exchange_direction|direction|pair|pair_id|side|side_id|type|type_id|"
    r"is_buy|is_sell|rate|back_rate)$",
    re.I,
)


def extract_offer_schema_samples(payload: object, limit: int = 30) -> list[dict[str, str]]:
    """Keep only currency/direction identifiers and reciprocal rate fields."""
    samples: list[dict[str, str]] = []

    def walk(node: object, depth: int = 0) -> None:
        if depth > 10 or len(samples) >= limit:
            return
        if isinstance(node, dict):
            if "rate" in node or "back_rate" in node:
                sample: dict[str, str] = {}
                for key, value in node.items():
                    if not SAFE_OFFER_KEYS.fullmatch(str(key)):
                        continue
                    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                        text = str(value).strip()
                        if text and len(text) <= 64:
                            sample[str(key)[:64]] = text
                    elif isinstance(value, dict):
                        for child_key, child_value in value.items():
                            if re.fullmatch(r"(id|code|symbol|name|currency)", str(child_key), re.I):
                                if isinstance(child_value, (str, int, float)) and not isinstance(child_value, bool):
                                    text = str(child_value).strip()
                                    if text and len(text) <= 64:
                                        sample[f"{key}.{child_key}"[:64]] = text
                if sample:
                    samples.append(sample)
            for child in node.values():
                if isinstance(child, (dict, list)):
                    walk(child, depth + 1)
        elif isinstance(node, list):
            for child in node:
                walk(child, depth + 1)

    walk(payload)
    return samples




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
        self.pending_bodies: list[tuple[str, str, str]] = []
        self.current_path = ""
        self.capture = {
            "deals_everyone_offers": {
                "request_count": 0,
                "response_statuses": [],
                "json_response_count": 0,
                "quote_fields": [],
                "offer_schema_samples": [],
            },
            "exchange_rub_usdt": {
                "request_count": 0,
                "response_statuses": [],
                "json_response_count": 0,
                "quote_fields": [],
                "offer_schema_samples": [],
            },
        }

    def close(self) -> None:
        self.ws.close()

    def event(self, message: dict) -> None:
        method = message.get("method", "")
        params = message.get("params", {})
        if method == "Page.frameNavigated":
            frame = params.get("frame", {})
            if not frame.get("parentId"):
                frame_url = frame.get("url", "")
                self.current_path = urlparse(frame_url).path
                print(f"NAV={safe_location(frame_url)}", flush=True)
        elif method == "Network.requestWillBeSent":
            request = params.get("request", {})
            parsed = urlparse(request.get("url", ""))
            if parsed.hostname != "sberkassa.site":
                return
            page_key = {
                "/deals": "deals_everyone_offers",
                "/exchange": "exchange_rub_usdt",
            }.get(self.current_path)
            if page_key:
                self.capture[page_key]["request_count"] += 1
            query = parse_qs(parsed.query, keep_blank_values=True)
            safe_query = {
                key: query[key][:3]
                for key in ("from", "to", "offset", "limit")
                if key in query
            }
            print(
                "REQUEST host=sberkassa.site path=%s method=%s type=%s safe_query=%s"
                % (
                    parsed.path,
                    request.get("method", "GET"),
                    params.get("type", "unknown"),
                    json.dumps(safe_query, ensure_ascii=False, separators=(",", ":")),
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
            page_key = {
                "/deals": "deals_everyone_offers",
                "/exchange": "exchange_rub_usdt",
            }.get(self.current_path) if host == "sberkassa.site" else None
            if page_key:
                statuses = self.capture[page_key]["response_statuses"]
                if len(statuses) < 40:
                    statuses.append(status)
            print(
                "HTTP_DIAG host=%s path=%s status=%s type=%s content_type=%s"
                % (host, parsed.path, status, params.get("type", "unknown"), mime),
                flush=True,
            )
            if (
                host == "sberkassa.site"
                and self.current_path in ("/deals", "/exchange")
                and params.get("type") in ("XHR", "Fetch")
                and "json" in mime
            ):
                self.pending_bodies.append((params.get("requestId", ""), parsed.path, page_key))

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
        for request_id, path, page_key in pending[:20]:
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
                if page_key:
                    captured = self.capture[page_key]
                    captured["json_response_count"] += 1
                    captured_fields = captured["quote_fields"]
                    remaining = max(0, 120 - len(captured_fields))
                    captured_fields.extend([[key, value] for key, value in fields[:remaining]])
                    if page_key:
                        captured["offer_schema_samples"] = extract_offer_schema_samples(payload)
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

        # Start on Sberkassa's own login page. The user completes its normal
        # E-ID redirect manually; wait for the browser to return to Sberkassa
        # after the identity provider was actually visited. Do not route via
        # Money Storage or submit any login form automatically.
        print("EID_HANDOFF=WAITING_FOR_SBERKASSA_CALLBACK", flush=True)
        auth_deadline = time.monotonic() + DEADLINE_SECONDS
        eid_provider_seen = False
        sberkassa_callback_seen = False
        while time.monotonic() < auth_deadline:
            auth_state = cdp.command(
                "Runtime.evaluate",
                {
                    "expression": "({url: location.href, ready: document.readyState})",
                    "returnByValue": True,
                },
            ).get("result", {}).get("value", {})
            auth_url = urlparse(auth_state.get("url", ""))
            auth_host = (auth_url.hostname or "").lower()
            if auth_url.scheme == "https" and (
                auth_host == "e-id.cards" or auth_host.endswith(".e-id.cards")
            ):
                eid_provider_seen = True
                print("EID_HANDOFF=IDENTITY_PROVIDER_SEEN", flush=True)
            if (
                eid_provider_seen
                and auth_url.scheme == "https"
                and (auth_host == "sberkassa.site" or auth_host.endswith(".sberkassa.site"))
            ):
                sberkassa_callback_seen = True
                break
            time.sleep(2)

        if not sberkassa_callback_seen:
            STATUS_FILE.write_text("AUTH_TIMEOUT", encoding="utf-8")
            print(
                "EID_HANDOFF_TIMEOUT=%s"
                % ("NO_SBERKASSA_CALLBACK" if eid_provider_seen else "EID_PROVIDER_NOT_SEEN"),
                flush=True,
            )
            return 1

        print("EID_HANDOFF=SBERKASSA_CALLBACK_CONFIRMED", flush=True)
        print("SBERKASSA_CALLBACK_PATH=%s" % auth_url.path, flush=True)
        print("SBERKASSA_LOGIN=READY_IN_ORIGINAL_TAB", flush=True)

        seen_deals = False
        seen_exchange = False
        last_target_activity = 0.0
        last_progress = 0.0
        last_page_key = ""
        last_marker_signature = None
        page_timestamps: dict[str, str | None] = {}
        page_markers: dict[str, list[str]] = {}
        page_quote_lines: dict[str, list[str]] = {}
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
                        .slice(0, 8),
                      quoteLines: (document.body ? document.body.innerText : "")
                        .split(/\\n/)
                        .map(x => x.trim())
                        .filter(x => x && x.length <= 200 && /(RUB|руб|₽|USDT|курс|rate|обмен)/i.test(x))
                        .slice(0, 30),
                      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
                      localNow: (() => {
                        const now = new Date();
                        return {
                          year: now.getFullYear(), month: now.getMonth() + 1, day: now.getDate(),
                          hour: now.getHours(), minute: now.getMinutes(), second: now.getSeconds()
                        };
                      })()
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
                page_markers[page_name] = markers
                page_quote_lines[page_name] = state.get("quoteLines", [])
                cdp.current_path = parsed.path
                signature = (page_name, tuple(markers))
                if signature != last_marker_signature or page_name != last_page_key:
                    print(
                        "PAGE_UPDATE_MARKERS page=%s title=%r lines=%s"
                        % (page_name, state.get("title", "")[:100], json.dumps(markers, ensure_ascii=False)),
                        flush=True,
                    )
                    try:
                        updated_at, update_text = parse_page_update_timestamp(
                            markers,
                            timezone_name=state.get("timezone", ""),
                            browser_local_now=state.get("localNow", {}),
                        )
                        page_timestamps[page_name] = updated_at.isoformat()
                        print(
                            "PAGE_TIMESTAMP_CONFIRMED page=%s updated_at=%s marker=%r"
                            % (page_name, updated_at.isoformat(), update_text),
                            flush=True,
                        )
                    except Exception as exc:
                        page_timestamps[page_name] = None
                        print(
                            "PAGE_TIMESTAMP_UNAVAILABLE page=%s reason=%s"
                            % (page_name, type(exc).__name__),
                            flush=True,
                        )
                    last_marker_signature = signature
                    last_page_key = page_name

            cdp.drain_json_bodies()

            now = time.monotonic()
            if now - last_progress >= 20:
                last_progress = now
                print(
                    "SBERKASSA_PROGRESS deals_seen=%s location=%s"
                    % (seen_deals, safe_location(url)),
                    flush=True,
                )

            if seen_deals and seen_exchange and now - last_target_activity >= 12:
                artifact = {
                    "schema_version": 2,
                    "captured_at_utc": datetime.now(timezone.utc).isoformat(),
                    "source": "sberkassa.site",
                    "quote_scope": "ERUB->RUB on /deals#tab-3 and RUB->USDT on /exchange",
                    "read_only": True,
                    "pages": {
                        "deals_everyone_offers": {
                            "url_path": "/deals#tab-3",
                            "page_updated_at": page_timestamps.get("deals_everyone_offers"),
                            "update_marker_lines": page_markers.get("deals_everyone_offers", []),
                            "visible_quote_lines": page_quote_lines.get("deals_everyone_offers", []),
                            **cdp.capture["deals_everyone_offers"],
                        },
                        "exchange_rub_usdt": {
                            "url_path": "/exchange",
                            "page_updated_at": page_timestamps.get("exchange_rub_usdt"),
                            "update_marker_lines": page_markers.get("exchange_rub_usdt", []),
                            "visible_quote_lines": page_quote_lines.get("exchange_rub_usdt", []),
                            **cdp.capture["exchange_rub_usdt"],
                        },
                    },
                    "limitations": [
                        "The ERUB/RUB everyone-offers page and RUB/USDT exchange page are captured independently",
                        "Currency/direction identifiers and reciprocal rate fields are captured in sanitized form; no exchange rate is inferred from an unverified field",
                        "No raw response body, offer amounts, commissions, volumes, reserves, liquidity, or authentication material is published",
                        "Page update markers are not yet correlated with a successful refresh",
                    ],
                }
                Path("sberkassa-current-inspection.json").write_text(
                    json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
                print("SBERKASSA_ARTIFACT_WRITTEN=sberkassa-current-inspection.json", flush=True)
                with open(Path(__import__("os").environ["GITHUB_STEP_SUMMARY"]), "a", encoding="utf-8") as summary:
                    summary.write("\n## Sberkassa read-only page inspection\n")
                    summary.write("- Both the ERUB -> RUB «Всем предлагают» page and the RUB -> USDT exchange page were visited in the manually authenticated standalone Chromium session.\n")
                    summary.write("- Captured sanitized currency/direction identifiers, quote-related fields, and page update-marker lines separately for each page.\n")
                    summary.write("- No raw response body, cookies, session tokens, authorization headers, or offer amounts were published.\n")
                    summary.write(f"- Deals page update timestamp: {page_timestamps.get('deals_everyone_offers') or 'not found'}\n")
                    summary.write(f"- Exchange page update timestamp: {page_timestamps.get('exchange_rub_usdt') or 'not found'}\n")
                    summary.write("- Offer creation timestamps are not used as page freshness.\n")
                    summary.write("- A visible timestamp still needs to be correlated with a successful refresh before enabling polling.\n")
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
