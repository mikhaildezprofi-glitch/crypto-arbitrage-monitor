from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from arbitrage_monitor.calculator import apply_step, calculate_route, five_step_route
from arbitrage_monitor.models import Quote, RouteStep


class CalculatorTests(unittest.TestCase):
    def quote(self, base, quote, rate, indicative=False, observed_at=None):
        return Quote(
            source="test",
            pair=f"{base}/{quote}",
            base_currency=base,
            quote_currency=quote,
            rate=Decimal(rate),
            observed_at=observed_at or datetime.now(timezone.utc),
            indicative_only=indicative,
        )

    def test_reverse_conversion_and_fee(self):
        step = RouteStep(
            "Winance", "USDT", "ERUB", self.quote("ERUB", "USDT", "0.04"),
            Decimal("1"), False
        )
        result = apply_step(Decimal("1000"), step)
        self.assertEqual(result.gross_output, Decimal("25000"))
        self.assertEqual(result.net_output, Decimal("24750"))

    def test_unknown_fee_is_not_assumed_zero(self):
        step = RouteStep(
            "BlackBit", "ECR", "USDT", self.quote("ECR", "USDT", "3.2"),
            None, True
        )
        with self.assertRaises(ValueError):
            apply_step(Decimal("100"), step)

    def test_route_currency_mismatch(self):
        step = RouteStep(
            "Wrong", "ECR", "USDT", self.quote("ERUB", "USDT", "0.04"),
            Decimal("0"), False
        )
        with self.assertRaises(ValueError):
            calculate_route(Decimal("1000"), "USDT", (step,))

    def test_future_quote_timestamp_blocks_full_route(self):
        future = datetime.now(timezone.utc) + timedelta(minutes=5)
        step = RouteStep(
            "Future quote", "USDT", "ERUB",
            self.quote("ERUB", "USDT", "0.04", observed_at=future),
            Decimal("0"), False
        )
        with self.assertRaisesRegex(ValueError, "stale"):
            calculate_route(Decimal("1000"), "USDT", (step,))

    def test_naive_and_aware_timestamps_are_compared_as_utc(self):
        now = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
        quote = self.quote(
            "ERUB", "USDT", "0.04",
            observed_at=datetime(2026, 11, 16, 11, 59)
        )
        self.assertEqual(quote.age_seconds(now), 60)

    def test_five_step_route_uses_exact_currency_sequence(self):
        pairs = {
            "money_storage": ("USDT", "ECR"),
            "blackbit": ("ECR", "USDT"),
            "winance": ("ERUB", "USDT"),
            "sberkassa_sell": ("ERUB", "RUB"),
            "sberkassa_exchange": ("RUB", "USDT"),
        }
        quotes = {
            key: self.quote(base, quote, "1")
            for key, (base, quote) in pairs.items()
        }
        fees = {key: Decimal("0") for key in pairs}
        steps = five_step_route(quotes, fees)
        self.assertEqual(
            [(step.input_currency, step.output_currency) for step in steps],
            [
                ("USDT", "ECR"),
                ("ECR", "USDT"),
                ("USDT", "ERUB"),
                ("ERUB", "RUB"),
                ("RUB", "USDT"),
            ],
        )
        self.assertTrue(steps[1].indicative_only)
        self.assertFalse(steps[2].indicative_only)
        self.assertEqual(steps[0].fee_percent, Decimal("0"))

    def test_everyone_offers_money_storage_commission_is_ignored(self):
        quotes = {
            "money_storage": self.quote("USDT", "ECR", "0.29154519"),
            "blackbit": self.quote("ECR", "USDT", "3.43", indicative=True),
            "winance": self.quote("ERUB", "USDT", "0.04"),
            "sberkassa_sell": self.quote("ERUB", "RUB", "1"),
            "sberkassa_exchange": self.quote("RUB", "USDT", "1"),
        }
        # Even if a source supplies a displayed commission, the project excludes it
        # from the Money Storage route step for the "Всем предлагают" tab.
        fees = {key: Decimal("0") for key in quotes}
        fees["money_storage"] = Decimal("0.5")
        steps = five_step_route(quotes, fees)
        self.assertEqual(steps[0].fee_percent, Decimal("0"))

    def test_five_step_route_rejects_missing_source_quote(self):
        with self.assertRaisesRegex(ValueError, "Missing quote: blackbit"):
            five_step_route(
                {"money_storage": self.quote("USDT", "ECR", "1")},
                {"money_storage": Decimal("0")},
            )

    def test_stale_quote_blocks_full_route(self):
        old = datetime.now(timezone.utc) - timedelta(hours=1)
        step = RouteStep(
            "Old quote", "USDT", "ERUB", self.quote("ERUB", "USDT", "0.04", observed_at=old),
            Decimal("0"), False
        )
        with self.assertRaisesRegex(ValueError, "stale"):
            calculate_route(Decimal("1000"), "USDT", (step,), max_quote_age_seconds=900)


if __name__ == "__main__":
    unittest.main()
