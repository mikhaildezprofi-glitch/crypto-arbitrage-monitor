"""Run a read-only four-source quote inspection from live browser snapshots and public APIs.

The browser snapshots must be created in the same workflow run. This script
never calculates final USDT, profit, or ROI because the route ends in RUB.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from arbitrage_monitor.providers.blackbit import BlackBitQuoteProvider
from arbitrage_monitor.providers.collection import FOUR_STEP_PROVIDER_KEYS, collect_quotes
from arbitrage_monitor.providers.money_storage import MoneyStorageSnapshotQuoteProvider
from arbitrage_monitor.providers.sberkassa import SberkassaSnapshotQuoteProvider
from arbitrage_monitor.providers.winance import WinanceQuoteProvider


def main() -> int:
    providers = {
        "money_storage": MoneyStorageSnapshotQuoteProvider(os.getenv("MONEY_STORAGE_SNAPSHOT", "money-storage-current-offers.json")),
        "blackbit": BlackBitQuoteProvider(),
        "winance": WinanceQuoteProvider(),
        "sberkassa_sell": SberkassaSnapshotQuoteProvider(os.getenv("SBERKASSA_SNAPSHOT", "sberkassa-current-inspection.json")),
    }
    batch = collect_quotes(providers, required_keys=FOUR_STEP_PROVIDER_KEYS)
    report = {
        "mode": "four_source_diagnostic",
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "route_complete": batch.complete,
        "profit_calculated": False,
        "roi_calculated": False,
        "fifth_source_requested": False,
        "steps": [],
    }
    for key in FOUR_STEP_PROVIDER_KEYS:
        quote = batch.quotes.get(key)
        if quote is None:
            report["steps"].append({
                "provider": key,
                "status": "unavailable",
                "reason": batch.errors.get(key, "No quote returned."),
            })
            continue
        report["steps"].append({
            "provider": key,
            "status": "collected",
            "pair": quote.pair,
            "rate": str(quote.rate),
            "observed_at": quote.observed_at.isoformat(),
            "indicative_only": quote.indicative_only,
        })
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if batch.complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
