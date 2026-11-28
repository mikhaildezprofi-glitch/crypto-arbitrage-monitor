#!/usr/bin/env python3
"""Check session_alive cookie names in Chromium SQLite databases, never values."""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXPECTED = {
    "money_storage": "storage.money",
    "sberkassa_deals": "sberkassa.site",
    "sberkassa_exchange": "sberkassa.site",
}


def domain_matches(expected_host: str, cookie_host: str) -> bool:
    domain = cookie_host.lower().lstrip(".")
    host = expected_host.lower()
    return host == domain or host.endswith("." + domain)


def inspect_profile(profile_dir: Path) -> dict[str, Any]:
    databases = sorted(path for path in profile_dir.rglob("Cookies") if path.is_file())
    found = {name: False for name in EXPECTED}
    readable = 0
    for database in databases:
        try:
            uri = database.resolve().as_uri() + "?mode=ro"
            with sqlite3.connect(uri, uri=True, timeout=3) as connection:
                rows = connection.execute(
                    "SELECT host_key, name FROM cookies WHERE name = ?",
                    ("session_alive",),
                ).fetchall()
            readable += 1
            for name, host in EXPECTED.items():
                if any(cookie_name == "session_alive" and domain_matches(host, cookie_host)
                       for cookie_host, cookie_name in rows):
                    found[name] = True
        except (sqlite3.Error, OSError):
            continue

    pages = {
        name: {
            "host": host,
            "cookie_database_count": len(databases),
            "session_alive_present": found[name],
        }
        for name, host in EXPECTED.items()
    }
    return {
        "schema_version": 1,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "cookie_databases_found": len(databases),
        "cookie_databases_readable": readable,
        "pages": pages,
        "all_pages_have_session_alive": readable > 0 and all(found.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile-dir", required=True)
    parser.add_argument("--report", default="session-alive-cookie-check.json")
    args = parser.parse_args()
    try:
        report = inspect_profile(Path(args.profile_dir))
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
            "SESSION_ALIVE_COOKIE page=%s present=%s"
            % (name, "YES" if page.get("session_alive_present") else "NO"),
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
