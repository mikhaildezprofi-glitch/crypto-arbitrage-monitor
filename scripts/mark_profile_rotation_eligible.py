#!/usr/bin/env python3
"""Create the profile-save marker after all tabs authenticate and cookies persist."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

EXPECTED_TABS = {
    "money_storage",
    "sberkassa_deals",
    "sberkassa_exchange",
}


def validate_profile_eligibility(auth_marker: str, cookie_report: dict[str, Any] | None) -> tuple[bool, str]:
    authenticated = {
        line.strip()
        for line in auth_marker.splitlines()
        if line.strip()
    }
    if not EXPECTED_TABS.issubset(authenticated):
        return False, "THREE_TAB_AUTHENTICATION_NOT_CONFIRMED"

    if not isinstance(cookie_report, dict) or cookie_report.get("all_pages_have_session_alive") is not True:
        return False, "SESSION_ALIVE_COOKIE_CHECK_FAILED"
    pages = cookie_report.get("pages")
    if not isinstance(pages, dict):
        return False, "SESSION_ALIVE_COOKIE_REPORT_INVALID"
    for name in EXPECTED_TABS:
        page = pages.get(name)
        if not isinstance(page, dict):
            return False, "SESSION_ALIVE_COOKIE_PAGE_MISSING"
        if page.get("session_alive_present") is not True:
            return False, "SESSION_ALIVE_COOKIE_MISSING_ON_PAGE"

    return True, "ALL_THREE_TABS_AUTHENTICATED_AND_SESSION_COOKIES_PRESENT"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--auth-marker", required=True)
    parser.add_argument("--cookie-report", required=True)
    parser.add_argument("--marker", default="profile-rotation-eligible.txt")
    args = parser.parse_args()

    try:
        auth_marker = Path(args.auth_marker).read_text(encoding="utf-8")
    except OSError:
        print("PROFILE_ROTATION_ELIGIBLE=NO reason=AUTH_MARKER_MISSING", flush=True)
        return 1
    try:
        cookie_report = json.loads(Path(args.cookie_report).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print("PROFILE_ROTATION_ELIGIBLE=NO reason=COOKIE_REPORT_UNREADABLE", flush=True)
        return 1

    eligible, reason = validate_profile_eligibility(auth_marker, cookie_report)
    if not eligible:
        print(f"PROFILE_ROTATION_ELIGIBLE=NO reason={reason}", flush=True)
        return 1
    Path(args.marker).write_text("profile_rotation_eligible", encoding="utf-8")
    print("PROFILE_ROTATION_ELIGIBLE=YES", flush=True)
    print("PROFILE_ROTATION_REASON=" + reason, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
