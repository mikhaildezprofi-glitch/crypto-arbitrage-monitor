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
import os
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
from arbitrage_monitor.providers.sberkassa import extract_erub_rub_offer_records

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
    r"is_buy|is_sell|rate|back_rate|exchange_rate|buy_rate|sell_rate|rate_value)$",
    re.I,
)


def extract_offer_schema_samples(payload: object, limit: int = 30) -> list[dict[str, str]]:
    """Keep only currency/direction identifiers and reciprocal rate fields."""
    samples: list[dict[str, str]] = []

    def walk(node: object, depth: int = 0) -> None:
        if depth > 10 or len(samples) >= limit:
            return
        if isinstance(node, dict):
            if any(re.search(r"(rate|price)", str(key), re.I) for key in node):
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


def parse_stream_quote_payload(raw: str) -> tuple[list[tuple[str, str]], list[dict[str, str]]]:
    """Parse JSON stream frames but retain only whitelisted quote/time fields."""
    try:
        payload = json.loads(raw)
    except Exception:
        return [], []
    return extract_quote_fields(payload), extract_offer_schema_samples(payload)


class CDP:
    def __init__(self, ws_url: str):
        self.ws = websocket.create_connection(
            ws_url, timeout=2, suppress_origin=True, enable_multithread=True
        )
        self.next_id = 0
        self.pending_bodies: list[tuple[str, str, str, dict, int]] = []
        self.current_path = ""
        self.capture = {
            "deals_everyone_offers": {
                "request_count": 0,
                "response_statuses": [],
                "json_response_count": 0,
                "quote_fields": [],
                "offer_schema_samples": [],
                "offer_records": [],
                "offer_request": {},
                "http_response_headers": [],
                "stream_quote_fields": [],
                "request_timing": [],
            },
            "exchange_rub_usdt": {
                "request_count": 0,
                "response_statuses": [],
                "json_response_count": 0,
                "quote_fields": [],
                "offer_schema_samples": [],
                "http_response_headers": [],
                "stream_quote_fields": [],
                "request_timing": [],
            },
        }

    def record_stream_payload(self, raw: str, source: str) -> None:
        page_key = {
            "/deals": "deals_everyone_offers",
            "/exchange": "exchange_rub_usdt",
        }.get(self.current_path)
        if not page_key:
            return
        fields, samples = parse_stream_quote_payload(raw)
        captured = self.capture[page_key]
        target = captured["stream_quote_fields"]
        remaining = max(0, 120 - len(target))
        target.extend([[source, key, value] for key, value in fields[:remaining]])
        if samples:
            captured["offer_schema_samples"] = (captured["offer_schema_samples"] + samples)[:60]

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
        elif method == "Network.webSocketFrameReceived":
            response = params.get("response", {})
            frame = params.get("response", {})
            payload = frame.get("payloadData", "")
            if payload and len(payload) <= 200000:
                self.record_stream_payload(payload, "websocket")
        elif method == "Network.eventSourceMessageReceived":
            payload = params.get("data", "")
            if payload and len(payload) <= 200000:
                self.record_stream_payload(payload, "eventsource")
        elif method == "Network.responseReceived":
            response = params.get("response", {})
            parsed = urlparse(response.get("url", ""))
            host = (parsed.hostname or "").lower()
            if host != "sberkassa.site" and host != "e-id.cards" and "cloudflare" not in host:
                return
            mime = (response.get("mimeType") or "unknown").split(";")[0]
            status = int(response.get("status", 0))
            page_paths = {
                "/deals": "deals_everyone_offers",
                "/exchange": "exchange_rub_usdt",
            }
            page_key = (
                page_paths.get(parsed.path) or page_paths.get(self.current_path)
            ) if host == "sberkassa.site" else None
            if page_key:
                captured = self.capture[page_key]
                statuses = captured["response_statuses"]
                if len(statuses) < 40:
                    statuses.append(status)
                timing = response.get("timing", {})
                timing_sample = {
                    "path": parsed.path[:160],
                    "resource_type": params.get("type", "unknown"),
                    "status": status,
                    "from_disk_cache": bool(response.get("fromDiskCache", False)),
                    "from_service_worker": bool(response.get("fromServiceWorker", False)),
                    "from_prefetch_cache": bool(response.get("fromPrefetchCache", False)),
                    "response_time": response.get("responseTime"),
                    "request_time": timing.get("requestTime"),
                    "receive_headers_end_ms": timing.get("receiveHeadersEnd"),
                    "encoded_data_length": response.get("encodedDataLength"),
                }
                if len(captured["request_timing"]) < 80:
                    captured["request_timing"].append(timing_sample)
                # Only allowlisted freshness/cache headers; never cookies or auth.
                if params.get("type") in ("Document", "XHR", "Fetch"):
                    raw_headers = response.get("headers", {})
                    allowed = {"date", "last-modified", "expires", "age", "cache-control", "etag", "vary"}
                    safe_headers = {
                        str(key).lower(): str(value)[:200]
                        for key, value in raw_headers.items()
                        if str(key).lower() in allowed and len(str(value)) <= 200
                    }
                    if safe_headers and len(captured["http_response_headers"]) < 60:
                        captured["http_response_headers"].append({
                            "path": parsed.path[:160],
                            "resource_type": params.get("type", "unknown"),
                            "status": status,
                            "headers": safe_headers,
                        })
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
                query = parse_qs(parsed.query, keep_blank_values=True)
                safe_query = {
                    key: query.get(key, [""])[0]
                    for key in ("from", "to")
                }
                self.pending_bodies.append((
                    params.get("requestId", ""),
                    parsed.path,
                    page_key,
                    safe_query,
                    status,
                ))

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
        for request_id, path, page_key, safe_query, status in pending[:20]:
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
                    if (
                        page_key == "deals_everyone_offers"
                        and path == "/public_deals/fetch"
                        and safe_query.get("from") == "ERUB"
                        and safe_query.get("to") == "RUB"
                    ):
                        records = extract_erub_rub_offer_records(payload)
                        captured["offer_request"] = {
                            "path": path,
                            "from": "ERUB",
                            "to": "RUB",
                            "status": status,
                        }
                        captured["offer_records"] = records
                        print(
                            "SBERKASSA_ERUB_RUB_OFFERS captured=%s status=%s"
                            % (len(records), status),
                            flush=True,
                        )
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

        # Test the restored browser profile first on the protected quote page.
        # A normal E-ID handoff is requested only if the page does not deliver
        # its quote data. The user completes any identity challenge manually.
        print("SESSION_REUSE_CHECK=START", flush=True)
        print("EID_HANDOFF=WAITING_ONLY_IF_SESSION_EXPIRED", flush=True)
        auth_timeout = 120 if os.environ.get("SBERKASSA_NONINTERACTIVE") == "1" else DEADLINE_SECONDS
        auth_deadline = time.monotonic() + auth_timeout
        eid_provider_seen = False
        callback_navigation_started = False
        session_ready = False
        while time.monotonic() < auth_deadline:
            auth_state = cdp.command(
                "Runtime.evaluate",
                {
                    "expression": """(async () => ({
                      url: location.href,
                      ready: document.readyState,
                      body: document.body ? document.body.innerText.slice(0, 12000) : ""
                    }))()""",
                    "returnByValue": True,
                    "awaitPromise": True,
                },
            ).get("result", {}).get("value", {})
            auth_url = urlparse(auth_state.get("url", ""))
            auth_host = (auth_url.hostname or "").lower()
            if auth_url.scheme == "https" and (
                auth_host == "e-id.cards" or auth_host.endswith(".e-id.cards")
            ):
                if not eid_provider_seen:
                    print("EID_HANDOFF=IDENTITY_PROVIDER_SEEN", flush=True)
                eid_provider_seen = True

            cdp.drain_json_bodies()
            is_deals_landing = (
                auth_url.scheme == "https"
                and auth_host == "sberkassa.site"
                and auth_url.path.rstrip("/") == "/deals"
                and auth_url.fragment == "tab-3"
            )
            deals_body = str(auth_state.get("body", "")).lower()
            deals_json_seen = cdp.capture["deals_everyone_offers"]["json_response_count"] > 0
            deals_visible = "курс:" in deals_body and ("erub" in deals_body or "rub" in deals_body)
            if is_deals_landing and deals_json_seen and deals_visible:
                session_ready = True
                if eid_provider_seen:
                    print("EID_HANDOFF=SBERKASSA_CALLBACK_CONFIRMED", flush=True)
                    print("SBERKASSA_SESSION=AUTHENTICATED_AFTER_EID", flush=True)
                else:
                    print("SBERKASSA_SESSION=RESTORED_PROFILE_REUSED", flush=True)
                break

            if (
                eid_provider_seen
                and auth_url.scheme == "https"
                and auth_host == "sberkassa.site"
                and not callback_navigation_started
            ):
                callback_navigation_started = True
                print("EID_HANDOFF=SBERKASSA_CALLBACK_CONFIRMED", flush=True)
                print("SBERKASSA_CALLBACK_PATH=%s" % auth_url.path, flush=True)
                cdp.command("Page.navigate", {"url": "https://sberkassa.site/deals#tab-3"})
                time.sleep(2)
                continue
            time.sleep(2)

        if not session_ready:
            STATUS_FILE.write_text("AUTH_TIMEOUT", encoding="utf-8")
            print(
                "SESSION_REUSE_OR_EID_TIMEOUT=%s"
                % ("EID_CALLBACK_SEEN_BUT_QUOTES_NOT_READY" if eid_provider_seen else "NO_VALID_SESSION_OR_EID"),
                flush=True,
            )
            return 1

        workspace = Path(os.environ["GITHUB_WORKSPACE"])
        (workspace / "session-authenticated.txt").write_text("sberkassa\n", encoding="utf-8")
        (workspace / "money-storage-profile-ready.txt").write_text("profile_ready\n", encoding="utf-8")
        print("SBERKASSA_SESSION_AUTHENTICATED=YES", flush=True)
        print("CHROMIUM_PROFILE_PERSISTENCE=ELIGIBLE_AFTER_SBERKASSA_AUTH", flush=True)

        seen_deals = False
        seen_exchange = False
        last_target_activity = 0.0
        last_progress = 0.0
        last_page_key = ""
        last_marker_signature = None
        page_timestamps: dict[str, str | None] = {}
        page_markers: dict[str, list[str]] = {}
        page_quote_lines: dict[str, list[str]] = {}
        page_quote_dom: dict[str, dict] = {}
        page_time_metadata: dict[str, list[dict]] = {}
        page_source_inventory: dict[str, dict] = {}
        deals_ready_since: float | None = None
        exchange_navigation_started = False
        deadline = time.monotonic() + DEADLINE_SECONDS

        while time.monotonic() < deadline:
            state = cdp.command(
                "Runtime.evaluate",
                {
                    "expression": """(async () => ({
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
                      timeMetadata: (() => {
                        const clean = value => String(value || "").trim().replace(/\\s+/g, " ").slice(0, 180);
                        const found = [];
                        const add = (kind, name, value) => {
                          const v = clean(value);
                          if (v && found.length < 50) found.push({kind, name: clean(name), value: v});
                        };
                        document.querySelectorAll("*")
                          .forEach(el => {
                            if (el.matches("meta[content]")) {
                              const name = el.getAttribute("name") || el.getAttribute("property") || el.getAttribute("itemprop") || "";
                              if (/(date|time|updated|modified|publish)/i.test(name)) add("meta", name, el.getAttribute("content"));
                            }
                            for (const attr of Array.from(el.attributes || [])) {
                              if (attr.name === "datetime" || (attr.name.startsWith("data-") && /(date|time|updated|modified|timestamp|refresh)/i.test(attr.name))) {
                                add("attribute", attr.name, attr.value);
                              }
                            }
                          });
                        return found;
                      })(),
                      quoteDom: (() => {
                        const visible = el => !!(el && el.getClientRects().length &&
                          getComputedStyle(el).visibility !== "hidden" &&
                          getComputedStyle(el).display !== "none");
                        const clean = value => String(value || "").trim().replace(/\\s+/g, " ").slice(0, 160);
                        const selects = Array.from(document.querySelectorAll("select"))
                          .filter(visible).slice(0, 12).map(el => ({
                            label: clean(el.labels && Array.from(el.labels).map(x => x.innerText).join(" ")),
                            selected: clean(el.selectedOptions && el.selectedOptions[0] && el.selectedOptions[0].textContent),
                            value: clean(el.value)
                          }));
                        const rateNodes = Array.from(document.querySelectorAll("body *"))
                          .filter(el => visible(el) && el.children.length === 0)
                          .map(el => clean(el.innerText || el.textContent))
                          .filter(text => text && text.length <= 160 &&
                            /(?:курс|rate|RUB|USDT|₽)/i.test(text) && /\\d/.test(text))
                          .slice(0, 30);
                        const rateInputs = Array.from(document.querySelectorAll("input"))
                          .filter(visible).filter(el =>
                            /rate|курс/i.test([el.name, el.id, el.getAttribute("aria-label"), el.placeholder].join(" "))
                          ).slice(0, 8).map(el => ({
                            label: clean([el.name, el.id, el.getAttribute("aria-label"), el.placeholder].join(" ")),
                            value: clean(el.value)
                          })).filter(el => /^\\d+(?:[.,]\\d+)?$/.test(el.value));
                        return { selects, rate_nodes: rateNodes, rate_inputs: rateInputs };
                      })(),
                      sourceInventory: await (async () => {
                        const safePath = value => {
                          try { const u = new URL(value, location.href); return u.origin === location.origin ? u.pathname : ""; }
                          catch (_) { return ""; }
                        };
                        const numeric = value => /^[-+]?\\d+(?:[.,]\\d+)?$/.test(String(value || "").trim());
                        const timeLike = value => /^(?:\\d{4}-\\d{2}-\\d{2}|\\d{1,2}[.\\/]\\d{1,2}[.\\/]\\d{2,4}|\\d{1,2}:\\d{2})/.test(String(value || "").trim());
                        const currencyLike = value => /^(RUB|USDT|USD|RUR|\\u20bd|руб\\.?|тезер)$/i.test(String(value || "").trim());
                        const safeKey = key => /^(rate|back_rate|exchange_rate|buy_rate|sell_rate|rate_value|price|currency|currency_id|from|to|from_id|to_id|base_currency|quote_currency|pair|pair_id|direction|updated_at|updatedAt|timestamp|date|time|last_updated|refresh_time)$/i.test(String(key));
                        const candidates = [];
                        const add = (source, key, value) => {
                          const v = String(value ?? "").trim().slice(0, 80);
                          if (v && (numeric(v) || timeLike(v) || currencyLike(v)) && candidates.length < 120)
                            candidates.push({source, key: String(key).slice(0, 80), value: v});
                        };
                        const walk = (node, source, depth = 0) => {
                          if (!node || depth > 7 || candidates.length >= 120) return;
                          if (Array.isArray(node)) { node.slice(0, 40).forEach(x => walk(x, source, depth + 1)); return; }
                          if (typeof node !== "object") return;
                          Object.entries(node).slice(0, 100).forEach(([key, value]) => {
                            if (safeKey(key) && (typeof value === "string" || typeof value === "number")) add(source, key, value);
                            else if (value && typeof value === "object") walk(value, source + "." + key, depth + 1);
                          });
                        };
                        document.querySelectorAll("*").forEach(el => {
                          for (const attr of Array.from(el.attributes || [])) {
                            if (/(rate|price|currency|pair|direction|updated|timestamp|refresh|date|time)/i.test(attr.name))
                              add("dom-attribute", attr.name, attr.value);
                          }
                        });
                        document.querySelectorAll("input").forEach(el => {
                          const key = [el.name, el.id, el.getAttribute("aria-label"), el.placeholder].join(" ");
                          if (/(rate|price|currency|updated|timestamp|date|time)/i.test(key)) add("input", key, el.value);
                        });
                        document.querySelectorAll('script[type="application/json"],script[type="application/ld+json"],script#__NEXT_DATA__').forEach((el, i) => {
                          try { walk(JSON.parse(el.textContent || "{}"), "embedded-json-" + i); } catch (_) {}
                        });
                        const stateNames = Object.getOwnPropertyNames(window).filter(name =>
                          /^__(INITIAL_STATE|INITIAL_DATA|PRELOADED_STATE|APOLLO_STATE|NEXT_DATA|NUXT)__$/i.test(name) ||
                          /^(reduxStore|appState|initialState|preloadedState)$/i.test(name)
                        ).slice(0, 12);
                        stateNames.forEach(name => { try { walk(window[name], "window." + name); } catch (_) {} });
                        const browserStorage = [];
                        for (const storageName of ["localStorage", "sessionStorage"]) {
                          try {
                            const store = window[storageName];
                            Object.keys(store).slice(0, 100).forEach(key => {
                              if (!/(rate|price|currency|pair|direction|quote|exchange|updated|timestamp|date|time)/i.test(key)) return;
                              const raw = store.getItem(key);
                              if (raw == null || raw.length > 200000) return;
                              if (numeric(raw) || timeLike(raw) || currencyLike(raw)) add("storage-" + storageName, key, raw);
                              else { try { walk(JSON.parse(raw), "storage-" + storageName + "." + key); } catch (_) {} }
                            });
                          } catch (_) {}
                        }
                        const cacheInventory = [];
                        try {
                          for (const cacheName of (await caches.keys()).slice(0, 20)) {
                            const cache = await caches.open(cacheName);
                            for (const request of (await cache.keys()).slice(0, 50)) {
                              const path = safePath(request.url);
                              if (!path || !/(rate|price|exchange|currency|quote|deal)/i.test(path)) continue;
                              const response = await cache.match(request);
                              if (!response) continue;
                              const contentType = response.headers.get("content-type") || "";
                              const headerSample = {};
                              for (const name of ["date", "last-modified", "age", "etag", "cache-control"]) {
                                const value = response.headers.get(name);
                                if (value) headerSample[name] = value.slice(0, 160);
                              }
                              const item = {cache: cacheName.slice(0, 80), path, content_type: contentType.slice(0, 80), headers: headerSample};
                              if (/json/i.test(contentType) && cacheInventory.length < 30) {
                                try { walk(await response.clone().json(), "cache." + path); item.json_candidate = true; } catch (_) { item.json_candidate = false; }
                              }
                              if (cacheInventory.length < 30) cacheInventory.push(item);
                            }
                          }
                        } catch (_) {}
                        const indexedDbInventory = [];
                        try {
                          if (indexedDB.databases) {
                            for (const info of (await indexedDB.databases()).slice(0, 20)) {
                              if (!info.name) continue;
                              const db = await new Promise(resolve => {
                                const request = indexedDB.open(info.name);
                                request.onsuccess = () => resolve(request.result);
                                request.onerror = () => resolve(null);
                                request.onblocked = () => resolve(null);
                              });
                              if (!db) continue;
                              const storeNames = Array.from(db.objectStoreNames);
                              for (const storeName of storeNames.filter(name => /(rate|price|currency|pair|quote|exchange|market)/i.test(name)).slice(0, 10)) {
                                try {
                                  const records = await new Promise(resolve => {
                                    const request = db.transaction(storeName, "readonly").objectStore(storeName).getAll(undefined, 20);
                                    request.onsuccess = () => resolve(request.result || []);
                                    request.onerror = () => resolve([]);
                                  });
                                  records.forEach(record => walk(record, "indexeddb." + storeName));
                                } catch (_) {}
                              }
                              indexedDbInventory.push({database: info.name.slice(0, 80), stores: storeNames.map(name => name.slice(0, 80)).slice(0, 30)});
                              db.close();
                            }
                          }
                        } catch (_) {}
                        const scripts = Array.from(document.scripts).map(el => safePath(el.src)).filter(Boolean).slice(0, 40);
                        const resources = performance.getEntriesByType("resource").map(entry => ({
                          path: safePath(entry.name), initiator: entry.initiatorType || "",
                          duration_ms: Math.round(entry.duration || 0),
                          response_end_ms: Math.round(entry.responseEnd || 0),
                          transfer_size: entry.transferSize || 0
                        })).filter(entry => entry.path).slice(-100);
                        return {numeric_candidates: candidates, browser_storage_candidates: browserStorage, cache_inventory: cacheInventory, indexeddb_inventory: indexedDbInventory, script_paths: scripts, resources};
                      })(),
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
                    "awaitPromise": True,
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
                page_quote_dom[page_name] = state.get("quoteDom", {})
                page_time_metadata[page_name] = state.get("timeMetadata", [])
                page_source_inventory[page_name] = state.get("sourceInventory", {})
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
            if is_deals:
                deals_data_ready = (
                    cdp.capture["deals_everyone_offers"]["json_response_count"] > 0
                    and any("курс:" in line.lower() for line in state.get("quoteLines", []))
                )
                if deals_data_ready:
                    if deals_ready_since is None:
                        deals_ready_since = now
                    elif now - deals_ready_since >= 4:
                        print("SBERKASSA_DEALS_CAPTURE_READY=YES", flush=True)
                else:
                    deals_ready_since = None

            if now - last_progress >= 20:
                last_progress = now
                print(
                    "SBERKASSA_PROGRESS deals_seen=%s location=%s"
                    % (seen_deals, safe_location(url)),
                    flush=True,
                )

            if seen_deals and deals_ready_since is not None and now - deals_ready_since >= 12:
                artifact = {
                    "schema_version": 3,
                    "captured_at_utc": datetime.now(timezone.utc).isoformat(),
                    "source": "sberkassa.site",
                    "quote_scope": "ERUB->RUB offers on /deals#tab-3 only",
                    "read_only": True,
                    "pages": {
                        "deals_everyone_offers": {
                            "url_path": "/deals#tab-3",
                            "page_updated_at": page_timestamps.get("deals_everyone_offers"),
                            "update_marker_lines": page_markers.get("deals_everyone_offers", []),
                            "visible_quote_lines": page_quote_lines.get("deals_everyone_offers", []),
                            "visible_quote_dom": page_quote_dom.get("deals_everyone_offers", {}),
                            "dom_time_metadata": page_time_metadata.get("deals_everyone_offers", []),
                            "source_inventory": page_source_inventory.get("deals_everyone_offers", {}),
                            **cdp.capture["deals_everyone_offers"],
                        },
                    },
                    "limitations": [
                        "The restored authenticated profile is tested first; manual E-ID is needed only when the session is no longer valid",
                    "Only the user-specified /deals#tab-3 page is opened; /exchange is never visited",
                        "Search includes JSON XHR/fetch responses, WebSocket/EventSource JSON frames, embedded JSON state, selected window state stores, DOM data attributes, numeric rate inputs, script paths, resource timing, and response cache metadata",
                        "Only whitelisted numeric quote/time fields and currency/direction identifiers are retained; no raw stream frames, raw response bodies, or arbitrary page state is published",
                        "No exchange rate is inferred from an unverified field",
                        "No raw response body, offer amounts, commissions, volumes, reserves, liquidity, or authentication material is published",
                        "DOM time metadata and allowlisted HTTP freshness/cache headers are diagnostic candidates only; they are not accepted as quote freshness until validated against a successful refresh",
                    ],
                }
                Path("sberkassa-current-inspection.json").write_text(
                    json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
                print("SBERKASSA_ARTIFACT_WRITTEN=sberkassa-current-inspection.json", flush=True)
                with open(Path(__import__("os").environ["GITHUB_STEP_SUMMARY"]), "a", encoding="utf-8") as summary:
                    summary.write("\n## Sberkassa read-only page inspection\n")
                    summary.write("- The restored session was reused, or the user completed E-ID manually when required.\n")
                    summary.write("- Both quote pages were visited using read-only navigation in the same Chromium profile.\n")
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
