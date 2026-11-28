"""Authentication-only check for the three shared Chromium tabs.

Reads only page URL/title metadata and boolean DOM authentication markers. It
never reads quote values, API response bodies, cookies, or submits forms.
CAPTCHA/E-ID/MFA remain user-operated.
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
    ("storage.money", "/deals"): ("money_storage", "https://storage.money/deals#tab-3"),
    ("sberkassa.site", "/deals"): ("sberkassa_deals", "https://sberkassa.site/deals#tab-3"),
    ("sberkassa.site", "/exchange"): ("sberkassa_exchange", "https://sberkassa.site/exchange"),
}
EXPECTED_NAMES = {name for name, _ in EXPECTED.values()}

# A navigation timing entry is immutable for a document. Some providers finish
# an E-ID callback inside an SPA without replacing that document. Therefore a
# stale 401/403 must not override positive, current DOM evidence that the
# protected application has rendered.
STATE_EXPRESSION = """(() => {
  const body = (document.body?.innerText || '').toLowerCase();
  const visible = element => {
    if (!element) return false;
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.visibility !== 'hidden' && style.display !== 'none'
      && rect.width > 0 && rect.height > 0;
  };
  const nav = performance.getEntriesByType('navigation')[0];
  const responseStatus = nav ? (nav.responseStatus || 0) : 0;
  const passwordFields = Array.from(document.querySelectorAll('input[type=password]')).filter(visible);
  const loginForms = passwordFields.filter(field => {
    const form = field.closest('form');
    if (!form || !visible(form)) return false;
    const action = String(form.getAttribute('action') || '').toLowerCase();
    const submit = Array.from(form.querySelectorAll('button, input[type=submit], [role=button]'))
      .filter(visible).map(el => String(el.innerText || el.value || el.getAttribute('aria-label') || '').toLowerCase()).join(' ');
    return /login|auth|signin|вход|авторизац/.test(action)
      || /sign in|log in|login|войти|вход/.test(submit);
  });
  const explicitAuthFailure = /session timed out|session expired|you must log in|please log in|unauthenticated|время сессии истекло|сессия истекла|не авторизован/.test(body);
  const visibleAuthControls = Array.from(document.querySelectorAll('a, button, [role=button]'))
    .filter(visible).map(el => String(el.innerText || el.textContent || el.getAttribute('aria-label') || '').toLowerCase());
  const hasLogoutControl = visibleAuthControls.some(text => /(^|\b)(log out|logout|sign out)(\b|$)|выйти/.test(text));
  const from = document.querySelector('#select_from');
  const to = document.querySelector('#select_to');
  const moneyCurrencyFormReady = !!(visible(from) && visible(to) && from.tomselect && to.tomselect);
  const sberkassaContentMarker = /предложен|обмен|курс|\busdt\b|\berub\b|\brub\b|рубл/.test(body);
  const challenge = /cf-turnstile|verify you are human|checking your browser|проверка браузера|доступ запрещ/.test(body);
  return {
    url: location.href,
    titlePresent: !!(document.title || '').trim(),
    bodyLength: body.trim().length,
    responseStatus,
    explicitAuthFailure,
    visiblePasswordFieldCount: passwordFields.length,
    visibleLoginFormCount: loginForms.length,
    hasLogoutControl,
    moneyCurrencyFormReady,
    sberkassaContentMarker,
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
                remote = message.get("result", {}).get("result", {})
                value = remote.get("value", {})
                return value if isinstance(value, dict) else {}
        raise TimeoutError("CDP evaluation timed out")
    finally:
        ws.close()


def navigate_to_expected(ws_url: str, target_url: str) -> None:
    """Navigate the same authenticated tab back to its protected route."""
    ws = websocket.create_connection(ws_url, timeout=5, suppress_origin=True)
    try:
        ws.send(json.dumps({
            "id": 2,
            "method": "Page.navigate",
            "params": {"url": target_url},
        }))
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            message = json.loads(ws.recv())
            if message.get("id") == 2:
                if message.get("error"):
                    raise RuntimeError("CDP Page.navigate failed")
                return
        raise TimeoutError("CDP Page.navigate timed out")
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
        return "POST_AUTH_REDIRECT_HOME" if host == key[0] and path in ("/", "/home", "/index.php") else "AUTH_HANDOFF_IN_PROGRESS"
    if state.get("ready") != "complete" or not state.get("titlePresent") or state.get("bodyLength", 0) < 10:
        return "PAGE_LOADING"

    # Positive site-specific DOM evidence takes precedence over the original
    # document's navigation status, which can remain 401/403 after an SPA E-ID
    # callback has completed without a full document navigation.
    if key[0] == "storage.money":
        if state.get("moneyCurrencyFormReady") and not state.get("explicitAuthFailure") and state.get("visibleLoginFormCount", 0) == 0:
            return "AUTHENTICATED"
    elif key[0] == "sberkassa.site":
        if (
            state.get("bodyLength", 0) >= 40
            and state.get("sberkassaContentMarker")
            and not state.get("explicitAuthFailure")
            and state.get("visibleLoginFormCount", 0) == 0
        ):
            return "AUTHENTICATED"

    if state.get("explicitAuthFailure") or state.get("visibleLoginFormCount", 0) > 0:
        return "LOGIN_REQUIRED"
    response_status = state.get("responseStatus", 0)
    if response_status not in (0, 200, 304):
        return "HTTP_STATUS_UNCONFIRMED"
    return "AUTHENTICATION_UNCONFIRMED"


def diagnostic(key: tuple[str, str], state: dict) -> str:
    return (
        f"status={state.get('responseStatus', 0)} "
        f"body_len={state.get('bodyLength', 0)} "
        f"password_fields={state.get('visiblePasswordFieldCount', 0)} "
        f"login_forms={state.get('visibleLoginFormCount', 0)} "
        f"money_form={int(bool(state.get('moneyCurrencyFormReady')))} "
        f"sberkassa_marker={int(bool(state.get('sberkassaContentMarker')))} "
        f"explicit_auth_failure={int(bool(state.get('explicitAuthFailure')))}"
    )


def main() -> int:
    print("SHARED_AUTH_PROBE=STARTED", flush=True)
    print("SHARED_AUTH_SCOPE=THREE_TABS_NO_QUOTE_COLLECTION", flush=True)
    print("SHARED_AUTH_DETECTION=SITE_DOM_MARKERS_WITH_STALE_NAV_STATUS_GUARD", flush=True)
    print("SHARED_AUTH_POST_EID_REDIRECT=AUTOMATIC_RETURN_TO_PROTECTED_ROUTE", flush=True)
    deadline = time.monotonic() + DEADLINE_SECONDS
    last_report = 0.0
    bound_ids: dict[tuple[str, str], str] = {}
    redirected_tabs: set[tuple[str, str]] = set()
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
                states = {name: "TAB_NOT_BOUND" for name in EXPECTED_NAMES}
            else:
                states = {}
                details = {}
                for key, (name, target_url) in EXPECTED.items():
                    item = by_id.get(bound_ids[key])
                    if not item:
                        states[name] = "TAB_TARGET_MISSING"
                        continue
                    try:
                        state = evaluate(item["webSocketDebuggerUrl"])
                        state_class = classify(key, state)
                        if state_class == "POST_AUTH_REDIRECT_HOME" and key not in redirected_tabs:
                            navigate_to_expected(item["webSocketDebuggerUrl"], target_url)
                            redirected_tabs.add(key)
                            print(f"SHARED_AUTH_POST_EID_NAVIGATION tab={name} result=STARTED target={key[0]}{key[1]}", flush=True)
                            states[name] = "POST_AUTH_NAVIGATION_STARTED"
                        else:
                            states[name] = state_class
                        details[name] = diagnostic(key, state)
                    except Exception as exc:
                        states[name] = "CDP_CHECK_RETRY"
                        details[name] = f"error={type(exc).__name__}"
            now = time.monotonic()
            if now - last_report >= 10:
                print("SHARED_AUTH_TAB_STATES " + " ".join(f"{k}={v}" for k, v in states.items()), flush=True)
                for name, detail in details.items() if len(bound_ids) == 3 else []:
                    print(f"SHARED_AUTH_TAB_DIAGNOSTIC {name} {detail}", flush=True)
                last_report = now
            if all(states.get(name) == "AUTHENTICATED" for name in EXPECTED_NAMES):
                STATUS_FILE.write_text("ALL_THREE_TABS_AUTHENTICATED", encoding="utf-8")
                Path("session-authenticated.txt").write_text(
                    "money_storage\nsberkassa_deals\nsberkassa_exchange\n", encoding="utf-8"
                )
                print("MONEY_STORAGE_AUTHENTICATED=YES", flush=True)
                print("SBERKASSA_DEALS_AUTHENTICATED=YES", flush=True)
                print("SBERKASSA_EXCHANGE_AUTHENTICATED=YES", flush=True)
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
