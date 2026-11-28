#!/usr/bin/env python3
"""Check only the presence of session_alive cookies in the three live tabs.

Cookie values, expiry values, paths, and other cookie attributes are never
printed or written to the report.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import websocket

CDP_ENDPOINT = "http://127.0.0.1:9222/json/list"
EXPECTED = {
    "money_storage": ("storage.money", "/deals"),
    "sberkassa_deals": ("sberkassa.site", "/deals"),
    "sberkassa_exchange": ("sberkassa.site", "/exchange"),
}


def page_targets() -> dict[str, dict]:
    request = urllib.request.Request(CDP_ENDPOINT, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as response:
        targets = json.loads(response.read().decode("utf-8"))
    found = {}
    for name, (host, path) in EXPECTED.items():
        for target in targets:
            parsed = urlparse(target.get("url", ""))
            if (
                target.get("type") == "page"
                and parsed.hostname == host
                and parsed.path.rstrip("/") == path
                and target.get("webSocketDebuggerUrl")
            ):
                found[name] = target
                break
    return found


def has_session_alive_cookie(ws_url: str, expected_host: str) -> bool:
    ws = websocket.create_connection(
        ws_url, timeout=5, suppress_origin=True, enable_multithread=True
    )
    try:
        for command_id, method in enumerate(("Network.enable", "Network.getAllCookies"), start=1):
            ws.send(json.dumps({"id": command_id, "method": method, "params": {}}))
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                message = json.loads(ws.recv())
                if message.get("id") != command_id:
                    continue
                if "error" in message:
                    raise RuntimeError("CDP_COOKIE_INSPECTION_FAILED")
                if method == "Network.getAllCookies":
                    cookies = message.get("result", {}).get("cookies", [])
                    for cookie in cookies:
                        domain = str(cookie.get("domain", "")).lower().lstrip(".")
                        if (
                            cookie.get("name") == "session_alive"
                            and (expected_host == domain or expected_host.endswith("." + domain))
                        ):
                            return True
                    return False
                break
            else:
                raise TimeoutError("CDP_COOKIE_INSPECTION_TIMEOUT")
    finally:
        ws.close()
    return False


def inspect() -> dict:
    targets = page_targets()
    pages = {}
    for name, (host, _path) in EXPECTED.items():
        target = targets.get(name)
        present = False
        if target:
            present = has_session_alive_cookie(target["webSocketDebuggerUrl"], host)
        pages[name] = {
            "host": host,
            "target_found": target is not None,
            "session_alive_present": present,
        }
    return {
        "schema_version": 1,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "pages": pages,
        "all_pages_have_session_alive": all(
            page["target_found"] and page["session_alive_present"]
            for page in pages.values()
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default="session-alive-cookie-check.json")
    args = parser.parse_args()
    try:
        report = inspect()
    except Exception as exc:
        report = {
            "schema_version": 1,
            "checked_at_utc": datetime.now(timezone.utc).isoformat(),
            "inspection_error": type(exc).__name__,
            "pages": {},
            "all_pages_have_session_alive": False,
        }
    Path(args.report).write_text(json.dumps(report, sort_keys=True, indent=2) + chr(10), encoding="utf-8")
    for name, page in report.get("pages", {}).items():
        print(
            "SESSION_ALIVE_COOKIE page=%s target=%s present=%s"
            % (
                name,
                "FOUND" if page.get("target_found") else "MISSING",
                "YES" if page.get("session_alive_present") else "NO",
            ),
            flush=True,
        )
    print(
        "SESSION_ALIVE_COOKIE_CHECK=%s"
        % ("PASS" if report["all_pages_have_session_alive"] else "FAIL"),
        flush=True,
    )
    return 0 if report["all_pages_have_session_alive"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
