import unittest
from datetime import datetime, timezone
from decimal import Decimal

from arbitrage_monitor.models import Quote
from arbitrage_monitor.providers.collection import (
    EXPECTED_PAIRS,
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
    base, quote_currency = EXPECTED_PAIRS[source]
    return Quote(
        source=source,
        pair=f"{base}/{quote_currency}",
        base_currency=base,
        quote_currency=quote_currency,
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

    def test_four_step_collection_does_not_request_or_require_fifth_source(self):
        from arbitrage_monitor.providers.collection import FOUR_STEP_PROVIDER_KEYS

        providers = self.make_providers()
        batch = collect_quotes(providers, required_keys=FOUR_STEP_PROVIDER_KEYS)

        self.assertTrue(batch.complete)
        self.assertEqual(batch.required_keys, FOUR_STEP_PROVIDER_KEYS)
        self.assertEqual(set(batch.quotes), set(FOUR_STEP_PROVIDER_KEYS))
        self.assertEqual(dict(batch.errors), {})
        self.assertEqual(providers["sberkassa_exchange"].calls, 0)
        self.assertTrue(
            all(providers[key].calls == 1 for key in FOUR_STEP_PROVIDER_KEYS)
        )

    def test_four_step_collection_ignores_missing_fifth_provider(self):
        from arbitrage_monitor.providers.collection import FOUR_STEP_PROVIDER_KEYS

        providers = self.make_providers()
        del providers["sberkassa_exchange"]
        batch = collect_quotes(providers, required_keys=FOUR_STEP_PROVIDER_KEYS)

        self.assertTrue(batch.complete)
        self.assertNotIn("sberkassa_exchange", batch.errors)

    def test_four_step_collection_still_fails_if_selected_source_is_missing(self):
        from arbitrage_monitor.providers.collection import FOUR_STEP_PROVIDER_KEYS

        providers = self.make_providers()
        del providers["sberkassa_sell"]
        batch = collect_quotes(providers, required_keys=FOUR_STEP_PROVIDER_KEYS)

        self.assertFalse(batch.complete)
        self.assertIn("sberkassa_sell", batch.errors)

    def test_default_collection_still_requires_all_five_sources(self):
        providers = self.make_providers()
        del providers["sberkassa_exchange"]
        batch = collect_quotes(providers)

        self.assertFalse(batch.complete)
        self.assertIn("sberkassa_exchange", batch.errors)

    def test_collection_rejects_unknown_or_duplicate_selection(self):
        with self.assertRaisesRegex(ValueError, "Unknown provider key"):
            collect_quotes({}, required_keys=("not_a_provider",))
        with self.assertRaisesRegex(ValueError, "unique"):
            collect_quotes({}, required_keys=("blackbit", "blackbit"))

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

    def test_rejects_wrong_currency_pair_for_provider_key(self):
        providers = self.make_providers()
        providers["winance"] = FakeProvider(
            quote=Quote(
                source="wrong",
                pair="ERUB/RUB",
                base_currency="ERUB",
                quote_currency="RUB",
                rate=Decimal("3"),
                observed_at=self.make_providers()["winance"].quote.observed_at,
            )
        )
        batch = collect_quotes(providers)
        self.assertFalse(batch.complete)
        self.assertNotIn("winance", batch.quotes)
        self.assertIn("expected ERUB/USDT", batch.errors["winance"])

    def test_rejects_non_positive_rate(self):
        providers = self.make_providers()
        providers["blackbit"] = FakeProvider(
            quote=Quote(
                source="BlackBit",
                pair="ECR/USDT",
                base_currency="ECR",
                quote_currency="USDT",
                rate=Decimal("0"),
                observed_at=datetime.now(timezone.utc),
            )
        )
        batch = collect_quotes(providers)
        self.assertFalse(batch.complete)
        self.assertNotIn("blackbit", batch.quotes)
        self.assertIn("non-positive", batch.errors["blackbit"])

    def test_batch_mappings_are_read_only(self):
        batch = collect_quotes(self.make_providers())
        with self.assertRaises(TypeError):
            batch.quotes["winance"] = make_quote("winance")


if __name__ == "__main__":
    unittest.main()
