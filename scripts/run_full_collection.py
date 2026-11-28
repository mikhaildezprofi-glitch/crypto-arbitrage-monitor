"""Run one read-only five-source collection cycle after the three parallel authenticated provider-browser jobs."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from decimal import Decimal

from arbitrage_monitor.providers.collection import REQUIRED_PROVIDER_KEYS, collect_quotes
from arbitrage_monitor.providers.factory import build_default_providers


def main() -> int:
    started = datetime.now(timezone.utc)
    providers = build_default_providers()
    batch = collect_quotes(providers)
    now = datetime.now(timezone.utc)
    max_age_raw = os.getenv("QUOTE_MAX_AGE_SECONDS", "").strip()
    max_age = int(max_age_raw) if max_age_raw else None

    sources = {}
    for key in REQUIRED_PROVIDER_KEYS:
        quote = batch.quotes.get(key)
        if quote is None:
            sources[key] = {"status": "unavailable", "error": batch.errors.get(key, "No quote returned")}
            continue
        age = quote.age_seconds(now)
        status = "fresh" if max_age is not None and age <= max_age else (
            "stale" if max_age is not None else "freshness_threshold_not_configured"
        )
        sources[key] = {
            "status": status,
            "source": quote.source,
            "pair": quote.pair,
            "rate": str(quote.rate),
            "observed_at_utc": quote.observed_at.astimezone(timezone.utc).isoformat(),
            "age_seconds": round(age, 3),
            "indicative_only": quote.indicative_only,
        }

    report = {
        "schema_version": 1,
        "mode": "READ_ONLY",
        "started_at_utc": started.isoformat(),
        "completed_at_utc": now.isoformat(),
        "required_sources": list(REQUIRED_PROVIDER_KEYS),
        "collection_complete": batch.complete,
        "quote_max_age_seconds": max_age,
        "sources": sources,
        "route_calculation": {
            "status": "not_evaluated",
            "reason": "Fees are not fully configured; unknown fees must not be assumed to be zero.",
        },
        "fund_moving_operations": False,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    output_path = os.getenv("FULL_COLLECTION_REPORT_PATH", "full-collection-report.json")
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write(rendered)
    print(rendered, end="")
    return 0 if batch.complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
