import unittest
from datetime import datetime, timezone
from decimal import Decimal

from arbitrage_monitor.models import Quote
from arbitrage_monitor.providers.collection import EXPECTED_PAIRS, REQUIRED_PROVIDER_KEYS
from arbitrage_monitor.storage import SQLiteQuoteStore
from arbitrage_monitor.cloud_worker import run_cycle


class FakeProvider:
    def __init__(self, quote=None, error=None):
        self.quote = quote
        self.error = error

    def fetch_quote(self):
        if self.error:
            raise self.error
        return self.quote


def make_quote(key, now):
    base, quote_currency = EXPECTED_PAIRS[key]
    return Quote(
        source=key,
        pair=f"{base}/{quote_currency}",
        base_currency=base,
        quote_currency=quote_currency,
        rate=Decimal("1"),
        observed_at=now,
        indicative_only=(key == "blackbit"),
    )


class CloudWorkerTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
        self.store = SQLiteQuoteStore(":memory:")
        self.fees = {
            "blackbit": Decimal("0"),
            "winance": Decimal("0"),
            "sberkassa_sell": Decimal("0"),
            "sberkassa_exchange": Decimal("0"),
        }

    def tearDown(self):
        self.store.close()

    def providers(self):
        return {
            key: FakeProvider(quote=make_quote(key, self.now))
            for key in REQUIRED_PROVIDER_KEYS
        }

    def test_complete_batch_calculates_and_persists(self):
        result = run_cycle(
            self.providers(),
            self.store,
            fees_percent=self.fees,
            now=self.now,
        )
        self.assertEqual(result["status"], "calculated")
        self.assertTrue(result["complete"])
        self.assertEqual(result["route"]["starting_amount"], "1000")
        self.assertTrue(result["route"]["indicative_only"])
        stored = self.store.latest_fresh_quotes(
            max_age_seconds=900,
            now=self.now,
        )
        self.assertEqual(set(stored), set(REQUIRED_PROVIDER_KEYS))

    def test_missing_provider_blocks_route(self):
        providers = self.providers()
        del providers["sberkassa_exchange"]
        result = run_cycle(
            providers,
            self.store,
            fees_percent=self.fees,
            now=self.now,
        )
        self.assertEqual(result["status"], "incomplete")
        self.assertIsNone(result["route"])
        self.assertIn("sberkassa_exchange", result["errors"])

    def test_unknown_fee_blocks_route(self):
        fees = dict(self.fees)
        fees["winance"] = None
        result = run_cycle(
            self.providers(),
            self.store,
            fees_percent=fees,
            now=self.now,
        )
        self.assertEqual(result["status"], "incomplete")
        self.assertIsNone(result["route"])
        self.assertIn("Fee for Winance is unknown", result["route_error"])

    def test_future_quote_blocks_route(self):
        providers = self.providers()
        future = datetime(2026, 11, 19, 12, 0, 1, tzinfo=timezone.utc)
        providers["winance"] = FakeProvider(quote=make_quote("winance", future))
        result = run_cycle(
            providers,
            self.store,
            fees_percent=self.fees,
            now=self.now,
        )
        self.assertEqual(result["status"], "incomplete")
        self.assertIsNone(result["route"])
        self.assertIn("future", result["route_error"].lower())

    def test_stale_quote_blocks_route(self):
        providers = self.providers()
        old = datetime(2026, 11, 19, 11, 0, tzinfo=timezone.utc)
        providers["winance"] = FakeProvider(quote=make_quote("winance", old))
        result = run_cycle(
            providers,
            self.store,
            fees_percent=self.fees,
            now=self.now,
        )
        self.assertEqual(result["status"], "incomplete")
        self.assertIsNone(result["route"])
        self.assertIn("stale", result["route_error"].lower())


if __name__ == "__main__":
    unittest.main()
