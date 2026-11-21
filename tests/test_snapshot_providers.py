import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from decimal import Decimal

from arbitrage_monitor.providers.money_storage import MoneyStorageSnapshotQuoteProvider
from arbitrage_monitor.providers.sberkassa import SberkassaSnapshotQuoteProvider


NOW = datetime.now(timezone.utc)


class SnapshotProviderTests(unittest.TestCase):
    def write_json(self, directory, name, payload):
        path = Path(directory) / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    def money_snapshot(self, *, observed_at=None, newest_offer_created_at=None, tab="everyone_offers"):
        return {
            "source": "money_storage",
            "tab": tab,
            "pair": "USDT/ECR",
            "rate": "0.291",
            "observed_at": (observed_at or NOW).isoformat(),
            "newest_offer_created_at": (newest_offer_created_at or NOW - timedelta(minutes=5)).isoformat(),
            "freshness_window_seconds": 900,
            "freshness_confirmed": True,
        }

    def test_money_storage_snapshot_uses_newest_offer_timestamp_for_freshness(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_json(directory, "money.json", self.money_snapshot())
            quote = MoneyStorageSnapshotQuoteProvider(path).fetch_quote()
        self.assertEqual(quote.pair, "USDT/ECR")
        self.assertEqual(quote.rate, Decimal("0.291"))
        self.assertEqual(quote.observed_at, NOW)

    def test_money_storage_snapshot_rejects_stale_newest_offer_even_when_collection_is_recent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_json(directory, "money.json", self.money_snapshot(
                newest_offer_created_at=NOW - timedelta(minutes=16)
            ))
            with self.assertRaisesRegex(RuntimeError, "newest offer is older"):
                MoneyStorageSnapshotQuoteProvider(path).fetch_quote()

    def test_money_storage_snapshot_rejects_stale_collection_time(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_json(directory, "money.json", self.money_snapshot(
                observed_at=NOW - timedelta(minutes=16),
                newest_offer_created_at=NOW - timedelta(minutes=17),
            ))
            with self.assertRaisesRegex(RuntimeError, "collection time is stale"):
                MoneyStorageSnapshotQuoteProvider(path).fetch_quote()

    def test_money_storage_snapshot_rejects_wrong_tab(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_json(directory, "money.json", self.money_snapshot(tab="my_offers"))
            with self.assertRaisesRegex(RuntimeError, "source or tab"):
                MoneyStorageSnapshotQuoteProvider(path).fetch_quote()

    def test_money_storage_snapshot_rejects_future_offer_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_json(directory, "money.json", self.money_snapshot(
                newest_offer_created_at=NOW + timedelta(seconds=1)
            ))
            with self.assertRaisesRegex(RuntimeError, "ahead of the collection clock"):
                MoneyStorageSnapshotQuoteProvider(path).fetch_quote()

    def sber_snapshot(self, *, created_at=None, request_from="ERUB", request_to="RUB"):
        created = (created_at or NOW).isoformat()
        return {
            "source": "sberkassa.site",
            "read_only": True,
            "captured_at_utc": NOW.isoformat(),
            "pages": {
                "deals_everyone_offers": {
                    "url_path": "/deals#tab-3",
                    "offer_request": {
                        "path": "/public_deals/fetch",
                        "from": request_from,
                        "to": request_to,
                        "status": 200,
                    },
                    "offer_records": [
                        {"back_rate": "25.0", "create_time": created},
                        {"back_rate": "27.0", "create_time": (NOW - timedelta(hours=2)).isoformat()},
                    ],
                }
            },
        }

    def test_sberkassa_snapshot_provider_uses_first_20_back_rates_and_create_time_freshness(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_json(directory, "sber.json", self.sber_snapshot())
            quote = SberkassaSnapshotQuoteProvider(path).fetch_quote()
        self.assertEqual(quote.pair, "ERUB/RUB")
        self.assertEqual(quote.rate, Decimal("26.0"))
        self.assertEqual(quote.observed_at, NOW)

    def test_sberkassa_snapshot_rejects_wrong_request_direction(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_json(directory, "sber.json", self.sber_snapshot(request_from="RUB", request_to="ERUB"))
            with self.assertRaisesRegex(RuntimeError, "verified ERUB"):
                SberkassaSnapshotQuoteProvider(path).fetch_quote()

    def test_sberkassa_snapshot_rejects_stale_snapshot(self):
        payload = self.sber_snapshot()
        payload["captured_at_utc"] = (NOW - timedelta(minutes=16)).isoformat()
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_json(directory, "sber.json", payload)
            with self.assertRaisesRegex(RuntimeError, "snapshot is future-dated or stale"):
                SberkassaSnapshotQuoteProvider(path).fetch_quote()

    def test_sberkassa_snapshot_rejects_stale_offers(self):
        payload = self.sber_snapshot(created_at=NOW - timedelta(minutes=16))
        payload["pages"]["deals_everyone_offers"]["offer_records"][1]["create_time"] = (
            NOW - timedelta(hours=2)
        ).isoformat()
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_json(directory, "sber.json", payload)
            with self.assertRaisesRegex(RuntimeError, "no_offer_created_within_15_minutes"):
                SberkassaSnapshotQuoteProvider(path).fetch_quote()


if __name__ == "__main__":
    unittest.main()
