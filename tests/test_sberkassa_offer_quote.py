import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from arbitrage_monitor.providers.sberkassa import build_erub_rub_offer_quote


NOW = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)


def offer(rate, created, source="ERUB", target="RUB"):
    return {
        "from_currency": source,
        "to_currency": target,
        "back_rate": rate,
        "create_time": created,
    }


class SberkassaOfferQuoteTests(unittest.TestCase):
    def test_any_offer_within_15_minutes_confirms_freshness(self):
        payload = {"data": [
            offer("25.0", (NOW - timedelta(hours=2)).isoformat()),
            offer("26.0", (NOW - timedelta(minutes=14)).isoformat()),
        ]}
        quote = build_erub_rub_offer_quote(payload, now=NOW)
        self.assertTrue(quote.available)
        self.assertEqual(quote.rate, Decimal("25.5"))
        self.assertEqual(quote.selected_offer_count, 2)

    def test_freshness_does_not_filter_first_twenty_average(self):
        rows = [offer("20", (NOW - timedelta(hours=3)).isoformat()) for _ in range(20)]
        rows.append(offer("40", (NOW - timedelta(minutes=5)).isoformat()))
        quote = build_erub_rub_offer_quote({"offers": rows}, now=NOW)
        self.assertTrue(quote.available)
        self.assertEqual(quote.rate, Decimal("20"))
        self.assertEqual(quote.selected_offer_count, 20)

    def test_stale_offers_keep_average_but_quote_is_unavailable(self):
        payload = {"offers": [offer("25", (NOW - timedelta(minutes=16)).isoformat())]}
        quote = build_erub_rub_offer_quote(payload, now=NOW)
        self.assertFalse(quote.available)
        self.assertEqual(quote.rate, Decimal("25"))
        self.assertEqual(quote.reason, "no_offer_created_within_15_minutes")

    def test_future_timestamp_does_not_confirm_freshness(self):
        payload = {"offers": [offer("25", (NOW + timedelta(seconds=1)).isoformat())]}
        quote = build_erub_rub_offer_quote(payload, now=NOW)
        self.assertFalse(quote.fresh)

    def test_wrong_direction_is_excluded(self):
        payload = {"offers": [
            offer("100", NOW.isoformat(), "RUB", "ERUB"),
            offer("25", NOW.isoformat(), "ERUB", "RUB"),
        ]}
        quote = build_erub_rub_offer_quote(payload, now=NOW)
        self.assertEqual(quote.rate, Decimal("25"))
        self.assertEqual(quote.matching_offer_count, 1)

    def test_invalid_back_rate_in_first_twenty_blocks_quote(self):
        rows = [offer("25", NOW.isoformat()) for _ in range(20)]
        rows[7]["back_rate"] = "NaN"
        quote = build_erub_rub_offer_quote({"offers": rows}, now=NOW)
        self.assertIsNone(quote.rate)
        self.assertEqual(quote.reason, "invalid_back_rate_in_first_20")

    def test_more_than_twenty_uses_only_first_twenty_rates(self):
        rows = [offer("10", NOW.isoformat()) for _ in range(20)]
        rows.append(offer("1000", NOW.isoformat()))
        quote = build_erub_rub_offer_quote({"offers": rows}, now=NOW)
        self.assertEqual(quote.rate, Decimal("10"))
        self.assertEqual(quote.selected_offer_count, 20)


if __name__ == "__main__":
    unittest.main()
