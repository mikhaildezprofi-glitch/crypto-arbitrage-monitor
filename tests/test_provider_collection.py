import unittest
from datetime import datetime, timezone
from decimal import Decimal

from arbitrage_monitor.models import Quote
from arbitrage_monitor.providers.collection import (
    REQUIRED_PROVIDER_KEYS,
    collect_quotes,
)


class FakeProvider:
    def __init__(self, quote=None, error=None):
        self.quote = quote
        self.error = error
        self.calls = 0

    def fetch_quote(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.quote


def make_quote(source):
    return Quote(
        source=source,
        pair="A/B",
        base_currency="A",
        quote_currency="B",
        rate=Decimal("2"),
        observed_at=datetime.now(timezone.utc),
    )


class QuoteCollectionTests(unittest.TestCase):
    def make_providers(self):
        return {
            key: FakeProvider(quote=make_quote(key))
            for key in REQUIRED_PROVIDER_KEYS
        }

    def test_collects_all_five_sources(self):
        providers = self.make_providers()
        batch = collect_quotes(providers)
        self.assertTrue(batch.complete)
        self.assertEqual(set(batch.quotes), set(REQUIRED_PROVIDER_KEYS))
        self.assertEqual(dict(batch.errors), {})
        self.assertTrue(all(provider.calls == 1 for provider in providers.values()))

    def test_one_failure_does_not_stop_other_sources(self):
        providers = self.make_providers()
        providers["blackbit"] = FakeProvider(error=TimeoutError("source timed out"))
        batch = collect_quotes(providers)
        self.assertFalse(batch.complete)
        self.assertNotIn("blackbit", batch.quotes)
        self.assertIn("timed out", batch.errors["blackbit"])
        self.assertEqual(
            set(batch.quotes),
            set(REQUIRED_PROVIDER_KEYS) - {"blackbit"},
        )
        self.assertTrue(all(provider.calls == 1 for provider in providers.values()))

    def test_missing_provider_is_explicit(self):
        providers = self.make_providers()
        del providers["sberkassa_exchange"]
        batch = collect_quotes(providers)
        self.assertFalse(batch.complete)
        self.assertNotIn("sberkassa_exchange", batch.quotes)
        self.assertEqual(
            batch.errors["sberkassa_exchange"],
            "Provider is not configured.",
        )

    def test_invalid_provider_result_is_rejected(self):
        providers = self.make_providers()
        providers["winance"] = FakeProvider(quote={"rate": "1"})
        batch = collect_quotes(providers)
        self.assertFalse(batch.complete)
        self.assertNotIn("winance", batch.quotes)
        self.assertIn("Quote instance", batch.errors["winance"])

    def test_batch_mappings_are_read_only(self):
        batch = collect_quotes(self.make_providers())
        with self.assertRaises(TypeError):
            batch.quotes["winance"] = make_quote("changed")


if __name__ == "__main__":
    unittest.main()
