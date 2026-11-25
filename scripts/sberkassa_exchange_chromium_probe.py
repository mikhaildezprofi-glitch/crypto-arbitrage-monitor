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
        # Start at the site's supported login entry point. Direct navigation
        # to /exchange can return an expired-session placeholder with no form.
        probe.command("Page.navigate", {"url": "https://sberkassa.site/"})
        print("SBERKASSA_EXCHANGE_PROBE_READY=YES", flush=True)
        print("SBERKASSA_EXCHANGE_LOGIN_ENTRY=HOME_PAGE", flush=True)
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
                if "время сессии истекло" in body or "session expired" in body:
                    print("SBERKASSA_EXCHANGE_SESSION_EXPIRED=YES", flush=True)
                    print("SBERKASSA_EXCHANGE_LOGIN_REQUIRED=HOME_PAGE_EID", flush=True)
                    eid_seen = False
                    callback_returned = False
                    probe.command("Page.navigate", {"url": "https://sberkassa.site/"})
                    time.sleep(2)
                    continue
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
        # Reuse the proven authenticated /exchange browser session and its
        # existing DOM quote reader. Replace only the former manual selection
        # pause with real pointer clicks dispatched through Chromium CDP.
        def evaluate_page(expression: str) -> dict:
            result = probe.command("Runtime.evaluate", {
                "expression": expression,
                "returnByValue": True,
            }).get("result", {}).get("value", {})
            return result if isinstance(result, dict) else {}

        def currency_code(value: object) -> str:
            text = str(value or "").upper()
            if re.search(r"\bUSDT\b|TETHER|ТЕЗЕР", text):
                return "USDT"
            if re.search(r"\bERUB\b|E-RUBLE|Е-РУБЛ", text):
                return "ERUB"
            if re.search(r"\bRUB\b|\bRUR\b|РОССИЙСКИЙ\s+РУБЛЬ|РУБЛЬ|₽", text):
                return "RUB"
            if re.search(r"\bUSD\b", text):
                return "USD"
            return ""

        page_state_expression = """(() => {
          const visible = el => {
            if (!el) return false;
            const s = getComputedStyle(el), r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0 && s.display !== 'none'
              && s.visibility !== 'hidden' && Number(s.opacity || 1) > 0;
          };
          const rect = el => {
            if (!visible(el)) return null;
            const r = el.getBoundingClientRect();
            return {x:r.left + r.width/2, y:r.top + r.height/2,
              width:r.width, height:r.height, visible:true};
          };
          const label = dir => {
            const text = document.querySelector('#currency_' + dir + 'SelectBoxItText');
            const select = document.querySelector('#currency_' + dir);
            return String((text && (text.innerText || text.textContent))
              || (select && select.selectedOptions && select.selectedOptions[0]
                && select.selectedOptions[0].textContent) || '').trim().slice(0,120);
          };
          const options = dir => {
            const root = document.querySelector('#currency_' + dir + 'SelectBoxItOptions');
            if (!root) return [];
            return Array.from(root.querySelectorAll('li')).map(li => {
              const clickable = li.querySelector('a,[role="option"]') || li;
              return {text:String(li.innerText || li.textContent || '').trim().slice(0,120),
                rect:rect(clickable)};
            }).filter(x => x.text);
          };
          const fromLabel = label('from'), toLabel = label('to');
          return {
            url:location.href,
            title:document.title,
            selected_labels:{from:fromLabel,to:toLabel},
            displayed_rate_text:String((document.querySelector('#current_rate')?.innerText || '').trim()).slice(0,180),
            triggers:{
              from:rect(document.querySelector('#currency_fromSelectBoxIt')),
              to:rect(document.querySelector('#currency_toSelectBoxIt'))
            },
            options:{from:options('from'),to:options('to')}
          };
        })()"""

        dom_diagnostic_expression = """(() => {
          const visible = el => {
            if (!el) return false;
            const s = getComputedStyle(el), r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0 && s.display !== 'none'
              && s.visibility !== 'hidden' && Number(s.opacity || 1) > 0;
          };
          const safeText = el => {
            const value = String(el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
            const tokens = value.match(/\b(?:RUB|RUR|USDT|USD|ERUB)\b|российский рубль|руб(?:ль|ля|лей)?\.?|тезер|tether|₽/gi) || [];
            return Array.from(new Set(tokens.map(token => token.slice(0, 40)))).join(' ').slice(0, 100);
          };
          const describe = el => {
            const r = el.getBoundingClientRect(), s = getComputedStyle(el);
            return {
              tag:el.tagName.toLowerCase(), id:String(el.id || '').slice(0,100),
              class:String(el.className && typeof el.className === 'string' ? el.className : '').slice(0,180),
              name:String(el.getAttribute('name') || '').slice(0,100),
              role:String(el.getAttribute('role') || '').slice(0,60),
              aria:String(el.getAttribute('aria-label') || '').slice(0,100),
              title:String(el.getAttribute('title') || '').slice(0,100),
              text:safeText(el), visible:visible(el),
              rect:{x:Math.round(r.x),y:Math.round(r.y),width:Math.round(r.width),height:Math.round(r.height)},
              display:s.display, visibility:s.visibility, pointerEvents:s.pointerEvents,
              disabled:!!el.disabled, tabindex:el.getAttribute('tabindex')
            };
          };
          const nodes = Array.from(document.querySelectorAll('body *'));
          const candidates = nodes.filter(el => {
            const meta = [el.id, el.className, el.getAttribute('name'), el.getAttribute('role'),
              el.getAttribute('aria-label'), el.getAttribute('title')].join(' ');
            const text = safeText(el);
            return /currency|selectbox|dropdown|from|to|select/i.test(String(meta))
              || (text && /\b(RUB|RUR|USDT|USD|ERUB)\b|руб|тезер|tether|₽/i.test(text))
              || ['SELECT','BUTTON','OPTION'].includes(el.tagName);
          }).slice(0,160).map(describe);
          const selects = Array.from(document.querySelectorAll('select')).slice(0,40).map(el => ({
            ...describe(el),
            options:Array.from(el.options || []).slice(0,80).map(o => ({
              text:String(o.textContent || '').trim().slice(0,100),
              value:String(o.value || '').slice(0,80), selected:!!o.selected, disabled:!!o.disabled
            }))
          }));
          const known = {};
          for (const id of ['currency_from','currency_to','currency_fromSelectBoxIt',
            'currency_toSelectBoxIt','currency_fromSelectBoxItOptions','currency_toSelectBoxItOptions',
            'current_rate']) {
            const el = document.getElementById(id);
            known[id] = el ? describe(el) : null;
          }
          const root = document.querySelector('.main-request');
          const mainRequestTree = root ? Array.from(root.querySelectorAll('*')).slice(0,120).map(el => ({
            ...describe(el), child_count:el.children.length,
            type:String(el.getAttribute('type') || '').slice(0,40)
          })) : [];
          const forms = Array.from(document.forms).slice(0,20).map(form => ({
            id:String(form.id || '').slice(0,80),
            class:String(typeof form.className === 'string' ? form.className : '').slice(0,120),
            method:String(form.method || '').toUpperCase(),
            action:(() => { try { return new URL(form.action, location.href).pathname; } catch (_) { return ''; } })(),
            controls:Array.from(form.querySelectorAll('input,select,button,textarea')).slice(0,60).map(el => ({
              tag:el.tagName.toLowerCase(),type:String(el.type || '').slice(0,40),
              id:String(el.id || '').slice(0,80),name:String(el.name || '').slice(0,80),
              role:String(el.getAttribute('role') || '').slice(0,40),
              visible:visible(el),disabled:!!el.disabled,
              text:safeText(el),placeholder:/currency|rate|amount|from|to/i.test(
                [el.id,el.name,el.placeholder].join(' ')) ? safeText({innerText:el.placeholder}) : ''
            }))
          }));
          const scripts = Array.from(document.scripts).map(el => {
            try { return new URL(el.src, location.href).pathname; } catch (_) { return ''; }
          }).filter(Boolean).slice(0,60);
          const iframes = Array.from(document.querySelectorAll('iframe')).slice(0,20).map(el => {
            let path = '';
            try { path = new URL(el.src, location.href).pathname; } catch (_) {}
            return {id:String(el.id || '').slice(0,80),class:String(el.className || '').slice(0,100),
              title:String(el.title || '').slice(0,80),path,visible:visible(el)};
          });
          const textMarkers = Array.from((document.body?.innerText || '').matchAll(
            /валют|курс|обмен|купить|продать|сумм|получ|отправ|войти|авторизац|exchange|rate|currency|amount|select|choose|continue|\\bRUB\\b|\\bUSDT\\b|\\bUSD\\b|\\bERUB\\b/gi
          )).map(match => match[0].slice(0,40)).slice(0,80);
          return {url:location.href,title:document.title,readyState:document.readyState,
            known_ids:known,selects,candidates,main_request_tree:mainRequestTree,
            forms,scripts,iframes,text_markers:textMarkers};
        })()"""

        def save_dom_diagnostic(reason: str) -> dict:
            diagnostic = evaluate_page(dom_diagnostic_expression)
            payload = {
                "schema_version": 1,
                "captured_at_utc": datetime.now(timezone.utc).isoformat(),
                "page": "/exchange",
                "reason": reason,
                "read_only": True,
                "diagnostic": diagnostic,
            }
            Path("sberkassa-exchange-dom-diagnostic.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            compact = {
                "url": diagnostic.get("url"),
                "readyState": diagnostic.get("readyState"),
                "known_ids": diagnostic.get("known_ids"),
                "selects": diagnostic.get("selects", [])[:20],
                "candidate_count": len(diagnostic.get("candidates", [])),
                "candidates": diagnostic.get("candidates", [])[:60],
            }
            print("SBERKASSA_EXCHANGE_DOM_DIAGNOSTIC=" +
                  json.dumps(compact, ensure_ascii=False), flush=True)
            print("SBERKASSA_EXCHANGE_DOM_DIAGNOSTIC_ARTIFACT=sberkassa-exchange-dom-diagnostic.json",
                  flush=True)
            return diagnostic

        def dispatch_click(rect: dict | None) -> bool:
            if not isinstance(rect, dict) or rect.get("visible") is not True:
                return False
            x, y = float(rect["x"]), float(rect["y"])
            probe.command("Input.dispatchMouseEvent", {
                "type": "mouseMoved", "x": x, "y": y,
            })
            probe.command("Input.dispatchMouseEvent", {
                "type": "mousePressed", "x": x, "y": y,
                "button": "left", "clickCount": 1,
            })
            probe.command("Input.dispatchMouseEvent", {
                "type": "mouseReleased", "x": x, "y": y,
                "button": "left", "clickCount": 1,
            })
            return True

        def select_currency(direction: str, wanted: str, timeout: float = 30) -> dict:
            deadline = time.monotonic() + timeout
            last_state: dict = {}
            clicked_trigger = False
            clicked_option = False
            while time.monotonic() < deadline:
                state = evaluate_page(page_state_expression)
                last_state = state
                if urlparse(state.get("url", "")).path.rstrip("/") != "/exchange":
                    time.sleep(0.25)
                    continue
                label = state.get("selected_labels", {}).get(direction, "")
                if currency_code(label) == wanted:
                    return {"selected": True, "label": label,
                            "trigger_clicked": clicked_trigger,
                            "option_clicked": clicked_option}
                if not clicked_trigger:
                    if not dispatch_click(state.get("triggers", {}).get(direction)):
                        time.sleep(0.5)
                        continue
                    clicked_trigger = True
                    time.sleep(0.25)
                    continue
                matching = next((item for item in state.get("options", {}).get(direction, [])
                                 if currency_code(item.get("text")) == wanted
                                 and isinstance(item.get("rect"), dict)
                                 and item["rect"].get("visible") is True), None)
                if matching:
                    if not dispatch_click(matching.get("rect")):
                        time.sleep(0.25)
                        continue
                    clicked_option = True
                    verify_deadline = time.monotonic() + 5
                    while time.monotonic() < verify_deadline:
                        verify = evaluate_page(page_state_expression)
                        label = verify.get("selected_labels", {}).get(direction, "")
                        if currency_code(label) == wanted:
                            return {"selected": True, "label": label,
                                    "trigger_clicked": clicked_trigger,
                                    "option_clicked": clicked_option}
                        time.sleep(0.2)
                    # A failed attempt may have closed the list; reopen it.
                    clicked_trigger = False
                else:
                    # The menu may still be animating or its option list may
                    # be rendered only after the real pointer event.
                    time.sleep(0.25)
            return {"selected": False,
                    "last_label": last_state.get("selected_labels", {}).get(direction, ""),
                    "trigger_clicked": clicked_trigger,
                    "option_clicked": clicked_option,
                    "available_options": [
                        x.get("text", "") for x in last_state.get("options", {}).get(direction, [])
                    ][:40]}

        selection = {
            "manual_selection_required": False,
            "selection_method": "chromium_cdp_pointer_clicks",
            "selected_pair": {},
            "selected_labels": {},
            "displayed_rate_text": "",
            "selection_confirmed": False,
            "sell_amount_entered": False,
            "exchange_submit_clicked": False,
        }
        samples = []
        print("SBERKASSA_EXCHANGE_AUTOMATIC_SELECTION=STARTED", flush=True)

        from_result = select_currency("from", "RUB")
        selection["from_selection"] = from_result
        print("SBERKASSA_EXCHANGE_FROM_SELECTION=" +
              json.dumps(from_result, ensure_ascii=False), flush=True)
        if from_result.get("selected") is True:
            to_result = select_currency("to", "USDT")
        else:
            to_result = {"selected": False, "reason": "from_currency_not_selected"}
        selection["to_selection"] = to_result
        print("SBERKASSA_EXCHANGE_TO_SELECTION=" +
              json.dumps(to_result, ensure_ascii=False), flush=True)

        if from_result.get("selected") is True and to_result.get("selected") is True:
            rate_deadline = time.monotonic() + 20
            while time.monotonic() < rate_deadline:
                state = evaluate_page(page_state_expression)
                labels = state.get("selected_labels", {})
                pair = {
                    "from": currency_code(labels.get("from", "")),
                    "to": currency_code(labels.get("to", "")),
                }
                rate_text = str(state.get("displayed_rate_text", "")).strip()
                if (urlparse(state.get("url", "")).path.rstrip("/") == "/exchange"
                        and pair == {"from": "RUB", "to": "USDT"} and rate_text):
                    observed_at = datetime.now(timezone.utc).isoformat()
                    selection.update({
                        "selected_pair": pair,
                        "selected_labels": labels,
                        "displayed_rate_text": rate_text,
                        "selection_confirmed": True,
                        "observed_at_utc": observed_at,
                    })
                    samples.append({"observed_at_utc": observed_at, "dom": state})
                    print("SBERKASSA_EXCHANGE_AUTOMATIC_PAIR_CONFIRMED=RUB_USDT", flush=True)
                    break
                time.sleep(0.5)

        if selection.get("selection_confirmed") is not True:
            save_dom_diagnostic("automatic_currency_selection_failed")
            STATUS_FILE.write_text("SBERKASSA_EXCHANGE_SELECTION_TIMEOUT", encoding="utf-8")
            print("SBERKASSA_EXCHANGE_SELECTION_TIMEOUT=YES", flush=True)
            return 1
        print("SBERKASSA_EXCHANGE_UI_SELECTION=" + json.dumps(selection, ensure_ascii=False), flush=True)
        print("SBERKASSA_EXCHANGE_DISPLAYED_RATE=" + selection["displayed_rate_text"], flush=True)
        print("SBERKASSA_EXCHANGE_RATE_CAPTURE_MODE=SINGLE_DISPLAYED_RATE", flush=True)
        print("SBERKASSA_EXCHANGE_RESULT_RECEIVED=YES", flush=True)

        artifact = {
            "schema_version": 1,
            "source": "sberkassa.site",
            "page": "/exchange",
            "read_only": True,
            "http_methods_allowed": ["GET"],
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "ui_selection": selection,
            "rate_capture_mode": "single_displayed_rate",
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
                "The probe automatically selected RUB -> USDT and captured the single displayed rate; it did not search or average offers, enter amounts, or click exchange/submit controls",
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
            summary.write("- The probe selected only the RUB and USDT currency dropdowns, did not enter amounts or submit an exchange, and blocked all non-GET requests to Sberkassa.\n")
            summary.write("- Captured sanitized visible form state and allowlisted quote/time fields only.\n")
            summary.write("- The displayed RUB -> USDT rate is recorded as a UI observation; quote freshness is not asserted by this discovery run.\n")
        STATUS_FILE.write_text("SBERKASSA_EXCHANGE_INSPECTION_COMPLETE", encoding="utf-8")
        print("SBERKASSA_EXCHANGE_INSPECTION_COMPLETE=YES", flush=True)
        return 0
    finally:
        probe.close()


if __name__ == "__main__":
    raise SystemExit(main())
