import unittest
from datetime import datetime, timezone
from decimal import Decimal

from arbitrage_monitor.providers.blackbit import (
    BlackBitQuoteError,
    BlackBitQuoteProvider,
    parse_ecr_usdt_pair_id,
    parse_order_book_rate,
    fetch_quote,
)


class BlackBitProviderTests(unittest.TestCase):
    def setUp(self):
        self.observed_at = datetime(2026, 11, 18, 8, 0, tzinfo=timezone.utc)

    def test_resolves_exact_ecr_usdt_pair_id(self):
        payload = {
            "currency_pairs": [
                {"id": "6", "name": "ECR/USDT", "base_currency": "ECR", "quoted_currency": "USDT"},
                {"id": "7", "name": "ECR/RUB", "base_currency": "ECR", "quoted_currency": "RUB"},
            ],
            "result": "ok",
            "status": 200,
        }
        self.assertEqual(parse_ecr_usdt_pair_id(payload), "6")

    def test_rejects_wrong_currency_direction(self):
        payload = {
            "currency_pairs": [
                {"id": "6", "name": "USDT/ECR", "base_currency": "USDT", "quoted_currency": "ECR"},
            ],
            "result": "ok",
            "status": 200,
        }
        with self.assertRaises(BlackBitQuoteError):
            parse_ecr_usdt_pair_id(payload)

    def test_rejects_ambiguous_matching_pairs(self):
        payload = {
            "currency_pairs": [
                {"id": "6", "name": "ECR/USDT"},
                {"id": "8", "name": "ECR/USDT"},
            ],
            "result": "ok",
            "status": 200,
        }
        with self.assertRaises(BlackBitQuoteError):
            parse_ecr_usdt_pair_id(payload)

    def test_uses_only_last_rate_and_marks_quote_indicative(self):
        payload = {
            "last_rate": 0.52901,
            "levels_buy": [{"rate": 0.1, "amount_base": "999999"}],
            "levels_sell": [{"rate": 0.9, "amount_base": "999999"}],
            "result": "ok",
            "status": 200,
        }
        quote = parse_order_book_rate(payload, pair_id="6", observed_at=self.observed_at)
        self.assertEqual(quote.rate, Decimal("0.52901"))
        self.assertEqual(quote.pair, "ECR/USDT")
        self.assertEqual(quote.source_pair_id, "6")
        self.assertTrue(quote.indicative_only)
        self.assertEqual(quote.observed_at, self.observed_at)

    def test_rejects_missing_zero_and_non_finite_last_rate(self):
        for invalid_rate in (None, 0, "NaN", "Infinity", "-Infinity"):
            with self.subTest(rate=invalid_rate):
                payload = {"last_rate": invalid_rate, "result": "ok", "status": 200}
                with self.assertRaises(BlackBitQuoteError):
                    parse_order_book_rate(payload, pair_id="6", observed_at=self.observed_at)

    def test_rejects_failed_api_envelope(self):
        payload = {"last_rate": 0.52901, "result": "error", "status": 500}
        with self.assertRaises(BlackBitQuoteError):
            parse_order_book_rate(payload, pair_id="6", observed_at=self.observed_at)

    def test_rejects_missing_currency_pair_list(self):
        with self.assertRaises(BlackBitQuoteError):
            parse_ecr_usdt_pair_id({"result": "ok", "status": 200})

    def test_provider_rejects_zero_timeout(self):
        with self.assertRaises(ValueError):
            BlackBitQuoteProvider(timeout_seconds=0)

    def test_fetch_quote_requests_resolved_pair_and_reads_displayed_last_rate(self):
        import json
        from unittest.mock import patch

        class FakeResponse:
            status = 200

            def __init__(self, payload):
                self.payload = json.dumps(payload).encode()

            def read(self):
                return self.payload

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        pairs = {
            "currency_pairs": [
                {"id": "6", "name": "ECR/USDT", "base_currency": "ECR", "quoted_currency": "USDT"}
            ],
            "result": "ok",
            "status": 200,
        }
        book = {"last_rate": "0.52901", "result": "ok", "status": 200}
        with patch(
            "arbitrage_monitor.providers.blackbit.urlopen",
            side_effect=[FakeResponse(pairs), FakeResponse(book)],
        ) as mocked:
            quote = fetch_quote(timeout_seconds=7)

        self.assertEqual(quote.rate, Decimal("0.52901"))
        self.assertTrue(quote.indicative_only)
        self.assertEqual(mocked.call_count, 2)
        self.assertTrue(mocked.call_args_list[0].args[0].full_url.endswith("/currency_pairs"))
        self.assertIn("currency_pair=6", mocked.call_args_list[1].args[0].full_url)
        self.assertIn("depth=100", mocked.call_args_list[1].args[0].full_url)


if __name__ == "__main__":
    unittest.main()
