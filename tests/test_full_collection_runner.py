from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

from arbitrage_monitor.models import Quote
from arbitrage_monitor.providers.collection import REQUIRED_PROVIDER_KEYS, QuoteBatch

from scripts import run_full_collection


def make_batch(*, stale_key: str | None = None, missing_key: str | None = None) -> QuoteBatch:
    now = datetime.now(timezone.utc)
    pairs = {
        "money_storage": ("USDT", "ECR", "1.1"),
        "blackbit": ("ECR", "USDT", "0.9"),
        "winance": ("USDT", "ERUB", "1.0"),
        "sberkassa_sell": ("ERUB", "RUB", "500"),
        "sberkassa_exchange": ("RUB", "USDT", "0.002"),
    }
    quotes = {}
    errors = {}
    for key, (base, quote_currency, rate) in pairs.items():
        if key == missing_key:
            errors[key] = "fixture missing"
            continue
        observed = now - (timedelta(seconds=901) if key == stale_key else timedelta(seconds=1))
        quotes[key] = Quote(
            source=key,
            pair=f"{base}/{quote_currency}",
            base_currency=base,
            quote_currency=quote_currency,
            rate=Decimal(rate),
            observed_at=observed,
            indicative_only=(key == "blackbit"),
        )
    return QuoteBatch(
        quotes=MappingProxyType(quotes),
        errors=MappingProxyType(errors),
    )


class FullCollectionRunnerTests(unittest.TestCase):
    def test_complete_fresh_batch_produces_normalized_pre_fee_route_estimate(self):
        now = datetime.now(timezone.utc)
        report = run_full_collection.build_report(
            make_batch(),
            started_at=now - timedelta(seconds=1),
            completed_at=now,
            max_quote_age_seconds=900,
        )
        self.assertTrue(report["collection_complete"])
        self.assertTrue(report["route_eligible"])
        route = report["route_calculation"]
        self.assertEqual(route["status"], "pre_fee_estimate")
        self.assertEqual(route["basis_amount_usdt"], "1")
        self.assertEqual(route["fee_assumption"], "temporary_zero_percent_for_all_five_steps")
        self.assertFalse(route["net_profit_calculated"])
        self.assertTrue(route["indicative_only"])
        self.assertEqual(len(route["steps"]), 5)

    def test_stale_quote_blocks_route_and_collection_success(self):
        now = datetime.now(timezone.utc)
        report = run_full_collection.build_report(
            make_batch(stale_key="winance"),
            started_at=now - timedelta(seconds=1),
            completed_at=now,
            max_quote_age_seconds=900,
        )
        self.assertTrue(report["collection_complete"])
        self.assertFalse(report["route_eligible"])
        self.assertEqual(report["sources"]["winance"]["status"], "stale")
        self.assertEqual(report["route_calculation"]["status"], "unavailable")

    def test_missing_quote_blocks_route(self):
        now = datetime.now(timezone.utc)
        report = run_full_collection.build_report(
            make_batch(missing_key="sberkassa_exchange"),
            started_at=now - timedelta(seconds=1),
            completed_at=now,
            max_quote_age_seconds=900,
        )
        self.assertFalse(report["collection_complete"])
        self.assertFalse(report["route_eligible"])

    def test_missing_freshness_threshold_blocks_route(self):
        now = datetime.now(timezone.utc)
        report = run_full_collection.build_report(
            make_batch(),
            started_at=now - timedelta(seconds=1),
            completed_at=now,
            max_quote_age_seconds=None,
        )
        self.assertFalse(report["route_eligible"])
        self.assertIn("not configured", report["route_calculation"]["reason"])

    def test_main_returns_failure_when_route_is_not_eligible(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            with patch.object(run_full_collection, "build_default_providers", return_value={}), patch.object(
                run_full_collection, "collect_quotes", return_value=make_batch(stale_key="blackbit")
            ), patch.dict(os.environ, {
                "QUOTE_MAX_AGE_SECONDS": "900",
                "FULL_COLLECTION_REPORT_PATH": str(output),
            }):
                self.assertEqual(run_full_collection.main(), 2)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertFalse(report["route_eligible"])


if __name__ == "__main__":
    unittest.main()
