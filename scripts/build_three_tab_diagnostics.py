#!/usr/bin/env python3
"""Build a per-tab, sanitized diagnostic report for the shared Chromium run.

Only allowlisted status values, quote summary fields, and selected log lines are
published. Raw response bodies, cookies, tokens, URLs with query strings, and
browser authentication material are never copied into the artifact.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SOURCES = {
    "money_storage": {
        "status_file": Path("/tmp/money-storage-status"),
        "log_file": Path("/tmp/money-storage-browser.log"),
        "expected_status": "OFFERS_READ_OK",
        "artifact": Path("money-storage-current-offers.json"),
        "log_pattern": re.compile(
            r"^(?:INITIAL_NAVIGATION=|BROWSER_READY=|SESSION_REUSE_CHECK=|"
            r"EID_HANDOFF=|PAGE_DIAG deals_form=|MONEY_STORAGE_|OFFERS_READ_|HTTP_DIAG |REQUEST |"
            r"PAGE_UPDATE_MARKERS |AUTH_REQUIRED|AUTH_TIMEOUT)"
        ),
    },
    "sberkassa_deals": {
        "status_file": Path("/tmp/sberkassa-sell-status"),
        "log_file": Path("/tmp/sberkassa-sell-browser.log"),
        "expected_status": "SBERKASSA_CAPTURE_COMPLETE",
        "artifact": Path("sberkassa-current-inspection.json"),
        "log_pattern": re.compile(
            r"^(?:NAV=|HTTP_DIAG |REQUEST |PAGE_UPDATE_MARKERS |"
            r"SBERKASSA_(?:SESSION|DEALS|ERUB_RUB|OFFERS|CAPTURE|ARTIFACT)|"
            r"AUTH_REQUIRED|AUTH_TIMEOUT|EID_HANDOFF=)"
        ),
    },
    "sberkassa_exchange": {
        "status_file": Path("/tmp/sberkassa-exchange-status"),
        "log_file": Path("/tmp/sberkassa-exchange-browser.log"),
        "expected_status": "SBERKASSA_EXCHANGE_INSPECTION_COMPLETE",
        "artifact": Path("sberkassa-exchange-inspection.json"),
        "log_pattern": re.compile(
            r"^(?:NAV=|HTTP_DIAG |SBERKASSA_EXCHANGE_(?:PROBE_READY|ENTRY|SCOPE|"
            r"SESSION|AUTOMATIC|FROM_SELECTION|TO_SELECTION|PAIR_CONFIRMED|"
            r"DISPLAYED_RATE|RATE_CAPTURE_MODE|RESULT_RECEIVED|"
            r"INSPECTION_COMPLETE|SELECTION_TIMEOUT|SESSION_EXPIRED|AUTH_TIMEOUT))"
        ),
    },
}

SECRET_MARKERS = re.compile(
    r"(?:bearer\s|authorization|cookie|set-cookie|password|passphrase|"
    r"secret|access[_ -]?token|refresh[_ -]?token)",
    re.I,
)
ANSI = re.compile(r"\x1b\[[0-9;]*m")
QUERY = re.compile(r"(https?://[^\s?]+)\?[^\s]+", re.I)
LONG_TOKEN = re.compile(r"(?<![A-Za-z0-9])[A-Fa-f0-9]{32,}(?![A-Za-z0-9])")


def read_status(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
        return value[:100] if value else "EMPTY_STATUS"
    except FileNotFoundError:
        return "STATUS_FILE_MISSING"
    except OSError:
        return "STATUS_FILE_UNREADABLE"


def sanitized_log(source: str, config: dict[str, Any], output: Path) -> list[str]:
    source_path: Path = config["log_file"]
    pattern: re.Pattern[str] = config["log_pattern"]
    selected: list[str] = []
    try:
        lines = source_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []

    for raw in lines:
        line = ANSI.sub("", raw).strip()
        if not line or not pattern.search(line) or SECRET_MARKERS.search(line):
            continue
        line = QUERY.sub(r"\1?[REDACTED]", line)
        line = LONG_TOKEN.sub("[REDACTED]", line)
        line = line[:500]
        selected.append(line)
    selected = selected[-100:]
    output.write_text("\n".join(selected) + ("\n" if selected else ""), encoding="utf-8")
    return selected


def money_storage_summary(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "pair": data.get("pair"),
        "tab": data.get("tab"),
        "offer_count": data.get("offer_count"),
        "average_rate": data.get("rate"),
        "observed_at_utc": data.get("observed_at"),
        "newest_offer_created_at_utc": data.get("newest_offer_created_at"),
        "freshness_window_seconds": data.get("freshness_window_seconds"),
        "freshness_confirmed": data.get("freshness_confirmed"),
    }


def sberkassa_deals_summary(data: dict[str, Any]) -> dict[str, Any]:
    page = data.get("pages", {}).get("deals_everyone_offers", {})
    quote = page.get("quote_validation", {})
    return {
        "direction": quote.get("direction"),
        "rate_field": quote.get("rate_field"),
        "matching_offer_count": quote.get("offer_count"),
        "averaged_offer_count": quote.get("averaged_offer_count"),
        "average_rate": quote.get("average_back_rate"),
        "fresh": quote.get("fresh"),
        "freshest_offer_created_at_utc": quote.get("freshest_offer_created_at_utc"),
        "freshest_offer_age_seconds": quote.get("freshest_offer_age_seconds"),
    }


def sberkassa_exchange_summary(data: dict[str, Any]) -> dict[str, Any]:
    latest = data.get("latest_dom_selection", {})
    return {
        "selected_pair": latest.get("selected_pair") or data.get("ui_selection", {}).get("selected_pair"),
        "displayed_rate": latest.get("displayed_rate_text") or data.get("ui_selection", {}).get("displayed_rate_text"),
        "observed_at_utc": latest.get("observed_at_utc") or data.get("observed_at_utc"),
        "page_loaded_at_utc": data.get("page_loaded_at_utc"),
        "freshness_basis": data.get("freshness_basis"),
        "rate_capture_mode": data.get("rate_capture_mode"),
    }


def load_artifact(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None, "ARTIFACT_NOT_OBJECT"
        return data, None
    except FileNotFoundError:
        return None, "ARTIFACT_MISSING"
    except (OSError, json.JSONDecodeError):
        return None, "ARTIFACT_UNREADABLE"


def build(output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = output_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "three_independent_read_only_tab_collectors",
        "historical_data_saved": False,
        "read_only": True,
        "sources": {},
    }

    summary_functions = {
        "money_storage": money_storage_summary,
        "sberkassa_deals": sberkassa_deals_summary,
        "sberkassa_exchange": sberkassa_exchange_summary,
    }
    complete = True
    for source, config in SOURCES.items():
        status = read_status(config["status_file"])
        log_name = f"{source}.log"
        log_lines = sanitized_log(source, config, logs_dir / log_name)
        artifact, artifact_error = load_artifact(config["artifact"])
        summary = summary_functions[source](artifact) if artifact else {}
        success = status == config["expected_status"] and artifact is not None
        complete = complete and success
        report["sources"][source] = {
            "status": "SUCCESS" if success else "INCOMPLETE",
            "collector_status": status,
            "artifact_status": "AVAILABLE" if artifact else artifact_error,
            "diagnostic_log": f"logs/{log_name}",
            "diagnostic_lines": len(log_lines),
            "quote": summary,
        }

    report["overall_status"] = "ALL_THREE_COLLECTORS_SUCCESS" if complete else "PARTIAL_OR_FAILED"
    report_path = output_dir / "three-tab-collector-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="three-tab-collector-diagnostics")
    args = parser.parse_args()
    report = build(Path(args.output_dir))
    for source, details in report["sources"].items():
        print(
            "COLLECTOR_DIAGNOSTIC source=%s status=%s collector=%s artifact=%s"
            % (source, details["status"], details["collector_status"], details["artifact_status"]),
            flush=True,
        )
    print("THREE_TAB_COLLECTION_STATUS=" + report["overall_status"], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
