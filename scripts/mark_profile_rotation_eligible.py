#!/usr/bin/env python3
"""Create the profile-rotation marker only after all three collectors validate.

The marker contains no authentication material. It gates encryption/cache save
so a partial run can never replace the last known-good browser profile.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

EXPECTED = {
    "money_storage": "OFFERS_READ_OK",
    "sberkassa_deals": "SBERKASSA_CAPTURE_COMPLETE",
    "sberkassa_exchange": "SBERKASSA_EXCHANGE_INSPECTION_COMPLETE",
}


def validate_report(report: dict[str, Any], cookie_report: dict[str, Any] | None = None) -> tuple[bool, str]:
    if report.get("overall_status") != "ALL_THREE_COLLECTORS_SUCCESS":
        return False, "OVERALL_STATUS_NOT_SUCCESS"
    if not isinstance(cookie_report, dict) or cookie_report.get("all_pages_have_session_alive") is not True:
        return False, "SESSION_ALIVE_COOKIE_CHECK_FAILED"
    cookie_pages = cookie_report.get("pages")
    if not isinstance(cookie_pages, dict) or any(
        cookie_pages.get(name, {}).get("session_alive_present") is not True
        or cookie_pages.get(name, {}).get("target_found") is not True
        for name in ("money_storage", "sberkassa_deals", "sberkassa_exchange")
    ):
        return False, "SESSION_ALIVE_COOKIE_MISSING_ON_PAGE"
    sources = report.get("sources")
    if not isinstance(sources, dict):
        return False, "SOURCES_MISSING"
    for name, expected_status in EXPECTED.items():
        source = sources.get(name)
        if not isinstance(source, dict):
            return False, f"{name.upper()}_REPORT_MISSING"
        if source.get("status") != "SUCCESS":
            return False, f"{name.upper()}_NOT_SUCCESS"
        if source.get("collector_status") != expected_status:
            return False, f"{name.upper()}_COLLECTOR_STATUS_INVALID"
        if source.get("artifact_status") != "AVAILABLE":
            return False, f"{name.upper()}_ARTIFACT_MISSING"
        quote = source.get("quote")
        if not isinstance(quote, dict) or not quote:
            return False, f"{name.upper()}_QUOTE_SUMMARY_MISSING"

    money = sources["money_storage"]["quote"]
    if money.get("pair") != "USDT/ECR" or money.get("freshness_confirmed") is not True:
        return False, "MONEY_STORAGE_QUOTE_NOT_VALIDATED"

    deals = sources["sberkassa_deals"]["quote"]
    if deals.get("direction") != "ERUB->RUB" or deals.get("fresh") is not True:
        return False, "SBERKASSA_DEALS_QUOTE_NOT_VALIDATED"

    exchange = sources["sberkassa_exchange"]["quote"]
    pair = exchange.get("selected_pair")
    if not isinstance(pair, dict) or pair.get("from") != "RUB" or pair.get("to") != "USDT":
        return False, "SBERKASSA_EXCHANGE_PAIR_NOT_VALIDATED"
    if not str(exchange.get("displayed_rate") or "").strip():
        return False, "SBERKASSA_EXCHANGE_RATE_MISSING"

    return True, "ALL_THREE_SOURCES_VALIDATED"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--marker", default="session-authenticated.txt")
    parser.add_argument("--cookie-report", required=True)
    args = parser.parse_args()
    try:
        report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print("PROFILE_ROTATION_ELIGIBLE=NO reason=REPORT_UNREADABLE", flush=True)
        return 1
    if not isinstance(report, dict):
        print("PROFILE_ROTATION_ELIGIBLE=NO reason=REPORT_NOT_OBJECT", flush=True)
        return 1
    try:
        cookie_report = json.loads(Path(args.cookie_report).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print("PROFILE_ROTATION_ELIGIBLE=NO reason=COOKIE_REPORT_UNREADABLE", flush=True)
        return 1
    eligible, reason = validate_report(report, cookie_report)
    if not eligible:
        print(f"PROFILE_ROTATION_ELIGIBLE=NO reason={reason}", flush=True)
        return 1
    Path(args.marker).write_text("profile_rotation_eligible",
        encoding="utf-8",
    )
    print("PROFILE_ROTATION_ELIGIBLE=YES", flush=True)
    print("PROFILE_ROTATION_REASON=" + reason, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
