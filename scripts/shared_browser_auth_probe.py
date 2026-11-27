"""Authentication-only check for the three shared Chromium tabs.

This probe reads only page URL/title metadata, navigation response status, and
boolean login/challenge markers. It never reads quote values or API responses,
never clicks, and never submits forms. CAPTCHA/E-ID/MFA remain user-operated.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import websocket

DEBUG_ENDPOINT = "http://127.0.0.1:9222/json/list"
STATUS_FILE = Path(os.environ.get("SHARED_AUTH_STATUS_FILE", "/tmp/shared-browser-auth-status"))
DEADLINE_SECONDS = int(os.environ.get("SHARED_AUTH_TIMEOUT_SECONDS", "1800"))

EXPECTED = {
    ("storage.money", "/deals"): "money_storage",
    ("sberkassa.site", "/deals"): "sberkassa_deals",
    ("sberkassa.site", "/exchange"): "sberkassa_exchange",
}

STATE_EXPRESSION = """(() => {
  const body = (document.body?.innerText || '').toLowerCase();
  const nav = performance.getEntriesByType('navigation')[0];
  const responseStatus = nav ? (nav.responseStatus || 0) : 0;
  const moneyAuthFailure = /session timed out|you must log in|please log in|unauthenticated/.test(body)
    || [401, 403].includes(responseStatus);
  const sberkassaLogin = /войти|авторизац|sign in|log in|login|session expired|время сессии истекло/.test(body);
  const challenge = /captcha|cf-turnstile|verify you are human|checking your browser|проверка браузера|доступ запрещ/.test(body);
  return {
    url: location.href,
    titlePresent: !!(document.title || '').trim(),
    bodyLength: body.trim().length,
    responseStatus,
    moneyAuthFailure,
    sberkassaLogin,
    challenge,
    ready: document.readyState
  };
})()"""


def page_targets() -> list[dict]:
    request = urllib.request.Request(DEBUG_ENDPOINT, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as response:
        items = json.loads(response.read().decode("utf-8"))
    return [
        item for item in items
        if item.get("type") == "page" and item.get("id") and item.get("webSocketDebuggerUrl")
    ]


def evaluate(ws_url: str) -> dict:
    ws = websocket.create_connection(ws_url, timeout=5, suppress_origin=True)
    try:
        ws.send(json.dumps({
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {"expression": STATE_EXPRESSION, "returnByValue": True},
        }))
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            message = json.loads(ws.recv())
            if message.get("id") == 1:
                return message.get("result", {}).get("result", {}).get("value", {})
        raise TimeoutError("CDP evaluation timed out")
    finally:
        ws.close()


def classify(key: tuple[str, str], state: dict) -> str:
    parsed = urlparse(str(state.get("url", "")))
    host = (parsed.hostname or "").lower()
    path = parsed.path.rstrip("/") or "/"
    if state.get("challenge"):
        return "CHALLENGE_PENDING"
    if host == "e-id.cards" or host.endswith(".e-id.cards"):
        return "EID_HANDOFF_IN_PROGRESS"
    if host != key[0] or path != key[1]:
        if host == key[0] and any(part in path.lower() for part in ("login", "auth", "oauth", "signin")):
            return "LOGIN_REQUIRED"
        return "AUTH_HANDOFF_IN_PROGRESS"
    if key[0] == "storage.money" and state.get("moneyAuthFailure"):
        return "LOGIN_REQUIRED"
    if key[0] == "sberkassa.site" and state.get("sberkassaLogin"):
        return "LOGIN_REQUIRED"
    if state.get("ready") != "complete" or not state.get("titlePresent") or state.get("bodyLength", 0) < 10:
        return "PAGE_LOADING"
    if key == ("storage.money", "/deals"):
        return "AUTHENTICATED" if state.get("responseStatus") == 200 else "HTTP_STATUS_UNCONFIRMED"
    if key == ("sberkassa.site", "/exchange"):
        return "AUTHENTICATED"
    # The deals tab shares the same sberkassa.site origin/session as /exchange.
    # This is a page-load check only, not a quote or protected-data check.
    return "LOADED_SHARED_ORIGIN"


def main() -> int:
    print("SHARED_AUTH_PROBE=STARTED", flush=True)
    print("SHARED_AUTH_SCOPE=THREE_TABS_NO_QUOTE_COLLECTION", flush=True)
    deadline = time.monotonic() + DEADLINE_SECONDS
    last_report = 0.0
    bound_ids: dict[tuple[str, str], str] = {}
    while time.monotonic() < deadline:
        try:
            targets = page_targets()
            by_id = {item["id"]: item for item in targets}
            if not bound_ids:
                initial: dict[tuple[str, str], dict] = {}
                for item in targets:
                    parsed = urlparse(item.get("url", ""))
                    key = ((parsed.hostname or "").lower(), parsed.path.rstrip("/") or "/")
                    if key in EXPECTED:
                        initial[key] = item
                initial_ids = [initial[key].get("id") for key in EXPECTED if key in initial]
                if set(initial) == set(EXPECTED) and len(initial_ids) == 3 and len(set(initial_ids)) == 3:
                    bound_ids = {key: initial[key]["id"] for key in EXPECTED}
                    print("SHARED_AUTH_THREE_DISTINCT_TARGET_IDS=VERIFIED", flush=True)
            if len(bound_ids) != 3 or len(set(bound_ids.values())) != 3:
                states = {name: "TAB_NOT_BOUND" for name in EXPECTED.values()}
            else:
                states = {}
                for key, name in EXPECTED.items():
                    item = by_id.get(bound_ids[key])
                    if not item:
                        states[name] = "TAB_TARGET_MISSING"
                        continue
                    try:
                        state = evaluate(item["webSocketDebuggerUrl"])
                        states[name] = classify(key, state)
                    except Exception:
                        states[name] = "CDP_CHECK_RETRY"
            now = time.monotonic()
            if now - last_report >= 10:
                print("SHARED_AUTH_TAB_STATES " + " ".join(f"{k}={v}" for k, v in states.items()), flush=True)
                last_report = now
            if (
                states.get("money_storage") == "AUTHENTICATED"
                and states.get("sberkassa_exchange") == "AUTHENTICATED"
                and states.get("sberkassa_deals") == "LOADED_SHARED_ORIGIN"
            ):
                STATUS_FILE.write_text("ALL_THREE_TABS_AUTHENTICATED", encoding="utf-8")
                Path("session-authenticated.txt").write_text(
                    "money_storage\nsberkassa_shared_origin\n", encoding="utf-8"
                )
                print("MONEY_STORAGE_AUTHENTICATED=YES", flush=True)
                print("SBERKASSA_SHARED_SESSION_AUTHENTICATED=YES", flush=True)
                print("SBERKASSA_DEALS_TAB_LOADED=YES", flush=True)
                print("ALL_THREE_TABS_AUTHENTICATED=YES", flush=True)
                return 0
        except Exception as exc:
            print(f"SHARED_AUTH_PROBE_RETRY error={type(exc).__name__}", flush=True)
        time.sleep(2)
    STATUS_FILE.write_text("AUTH_TIMEOUT", encoding="utf-8")
    print("SHARED_AUTH_TIMEOUT=YES", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
