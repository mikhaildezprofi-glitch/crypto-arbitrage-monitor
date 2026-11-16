import unittest
from datetime import datetime, timezone
from decimal import Decimal

from arbitrage_monitor.providers.winance import (
    WinanceQuoteError,
    parse_winance_response,
)


class WinanceProviderTests(unittest.TestCase):
    def setUp(self):
        self.observed_at = datetime(2026, 11, 16, tzinfo=timezone.utc)

    def test_parses_pair_18_erub_usdt(self):
        payload = {
            "currency_pairs": [
                {"id": "18", "name": "ERUB/USDT", "rate": 0.037124},
                {"id": "19", "name": "ERUB/RUB", "rate": 3.01},
            ],
            "result": "ok",
            "status": 200,
        }
        quote = parse_winance_response(payload, self.observed_at)
        self.assertEqual(quote.source_pair_id, "18")
        self.assertEqual(quote.pair, "ERUB/USDT")
        self.assertEqual(quote.rate, Decimal("0.037124"))

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
                {"id": "19", "name": "ERUB/USDT", "rate": 0.037124},
            ]
        }
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
