import unittest
from datetime import datetime, timezone
from decimal import Decimal

from arbitrage_monitor.providers.winance import (
    POLL_SECONDS,
    WinanceQuoteError,
    parse_winance_response,
)


class WinanceProviderTests(unittest.TestCase):
    def setUp(self):
        self.observed_at = datetime(2026, 11, 16, tzinfo=timezone.utc)

    def live_shape_payload(self):
        # Sanitized fixture matching the public currency_pairs response shape.
        return {
            "currency_pairs": [
                {
                    "base_currency": "ERUB",
                    "base_id": 2010,
                    "id": "18",
                    "minimum_amount": 0,
                    "name": "ERUB/USDT",
                    "quoted_currency": "USDT",
                    "quoted_id": 4840,
                    "rate": 0.037335,
                    "volume_base": "2910883.64841983",
                    "volume_quoted": "59406.016613",
                },
                {
                    "base_currency": "ERUB",
                    "base_id": 2010,
                    "id": "19",
                    "minimum_amount": 0,
                    "name": "ERUB/RUB",
                    "quoted_currency": "RUB",
                    "quoted_id": 643,
                    "rate": 3,
                    "volume_base": "1347857.82683239",
                    "volume_quoted": "1202704.84",
                },
            ],
            "result": "ok",
            "status": 200,
        }

    def test_parses_live_api_shape_and_only_pair_18(self):
        quote = parse_winance_response(self.live_shape_payload(), self.observed_at)
        self.assertEqual(quote.source_pair_id, "18")
        self.assertEqual(quote.pair, "ERUB/USDT")
        self.assertEqual(quote.base_currency, "ERUB")
        self.assertEqual(quote.quote_currency, "USDT")
        self.assertEqual(quote.rate, Decimal("0.037335"))
        self.assertEqual(quote.observed_at, self.observed_at)

    def test_poll_interval_is_five_minutes(self):
        self.assertEqual(POLL_SECONDS, 300)

    def test_rejects_wrong_symbol_even_when_id_matches(self):
        payload = {
            "currency_pairs": [
                {"id": "18", "name": "ERUB/RUB", "rate": 3.01},
            ]
        }
        with self.assertRaises(WinanceQuoteError):
            parse_winance_response(payload, self.observed_at)

    def test_rejects_correct_symbol_with_wrong_id(self):
        payload = {
            "currency_pairs": [
                {"id": "19", "name": "ERUB/USDT", "rate": 0.037335},
            ]
        }
        with self.assertRaises(WinanceQuoteError):
            parse_winance_response(payload, self.observed_at)

    def test_rejects_pair_id_with_conflicting_currency_fields(self):
        payload = {
            "currency_pairs": [
                {
                    "id": "18",
                    "base_currency": "ERUB",
                    "quoted_currency": "RUB",
                    "rate": 3.0,
                },
            ]
        }
        with self.assertRaises(WinanceQuoteError):
            parse_winance_response(payload, self.observed_at)

    def test_rejects_pair_id_without_any_pair_identity_fields(self):
        payload = {"currency_pairs": [{"id": "18", "rate": 0.037335}]}
        with self.assertRaises(WinanceQuoteError):
            parse_winance_response(payload, self.observed_at)

    def test_rejects_missing_or_nonpositive_rate(self):
        payload = {
            "currency_pairs": [
                {"id": "18", "name": "ERUB/USDT", "rate": 0},
            ]
        }
        with self.assertRaises(WinanceQuoteError):
            parse_winance_response(payload, self.observed_at)


if __name__ == "__main__":
    unittest.main()
