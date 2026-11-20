import unittest
from datetime import datetime, timezone
from decimal import Decimal

from arbitrage_monitor.providers.money_storage import (
    MONEY_STORAGE_PAGE_SIZE,
    MONEY_STORAGE_POLL_SECONDS,
    MoneyStorageQuoteProvider,
    average_first_20_offer_rate,
    parse_public_offer,
    parse_public_offers,
    parse_public_offer_pages,
)


def raw_offer(**overrides):
    row = {
        "src_amount": "1000",
        "src_currency": "ECR",
        "dst_amount": "3430",
        "dst_currency": "USDT",
        "rate": "0.29154519",
        "back_rate": "3.43",
        "commission": "17.15",
        "commission_currency": "USDT",
        "create_time": 1794843483,
    }
    row.update(overrides)
    return row


class MoneyStorageParserTests(unittest.TestCase):
    def test_maps_raw_pair_to_displayed_user_direction(self):
        offer = parse_public_offer(raw_offer())
        self.assertEqual(offer.pair, "USDT/ECR")
        self.assertEqual(offer.give_amount, Decimal("3430"))
        self.assertEqual(offer.receive_amount, Decimal("1000"))
        self.assertEqual(offer.rate, Decimal("0.29154519"))
        self.assertEqual(offer.commission, Decimal("17.15"))
        self.assertEqual(offer.commission_currency, "USDT")

    def test_preserves_unknown_commission_instead_of_zero(self):
        row = raw_offer()
        row.pop("commission")
        row.pop("commission_currency")
        offer = parse_public_offer(row)
        self.assertIsNone(offer.commission)
        self.assertIsNone(offer.commission_currency)

    def test_rejects_wrong_raw_direction(self):
        with self.assertRaisesRegex(ValueError, "Expected raw Money Storage pair"):
            parse_public_offer(raw_offer(src_currency="USDT", dst_currency="ECR"))

    def test_rejects_non_positive_amount(self):
        with self.assertRaisesRegex(ValueError, "amounts must be positive"):
            parse_public_offer(raw_offer(dst_amount="0"))

    def test_rejects_negative_commission(self):
        with self.assertRaisesRegex(ValueError, "cannot be negative"):
            parse_public_offer(raw_offer(commission="-1"))

    def test_rejects_half_specified_commission(self):
        with self.assertRaisesRegex(ValueError, "must be supplied together"):
            parse_public_offer(raw_offer(commission_currency=None))

    def test_extracts_only_target_direction_and_keeps_order(self):
        payload = {
            "data": [
                raw_offer(rate="0.29"),
                raw_offer(dst_amount="168.07", src_amount="49", rate="0.30"),
                raw_offer(src_currency="USDT", dst_currency="ECR"),
            ]
        }
        offers = parse_public_offers(payload)
        self.assertEqual(len(offers), 2)
        self.assertEqual(offers[0].rate, Decimal("0.29"))
        self.assertEqual(offers[1].rate, Decimal("0.30"))

    def test_rejects_empty_commission_currency(self):
        with self.assertRaisesRegex(ValueError, "must be supplied together"):
            parse_public_offer(raw_offer(commission="1", commission_currency=""))

    def test_parses_multiple_pages_without_deduplicating_offers(self):
        first = {"data": [raw_offer()]}
        second = {"data": [raw_offer()]}
        offers = parse_public_offer_pages([first, second])
        self.assertEqual(len(offers), 2)
        self.assertEqual(offers[0].created_at, offers[1].created_at)

    def test_average_is_arithmetic_mean_of_first_20_rates(self):
        offers = tuple(
            parse_public_offer(raw_offer(rate=str(Decimal("0.20") + Decimal(i) / 100)))
            for i in range(25)
        )
        observed = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
        quote = average_first_20_offer_rate(offers, observed_at=observed)
        expected = sum((offer.rate for offer in offers[:20]), Decimal("0")) / Decimal("20")
        self.assertEqual(quote.rate, expected)
        self.assertEqual(quote.pair, "USDT/ECR")
        self.assertEqual(quote.observed_at, observed)

    def test_average_accepts_short_page_and_uses_all_available_offers(self):
        offers = (
            parse_public_offer(raw_offer(rate="0.20")),
            parse_public_offer(raw_offer(rate="0.30")),
        )
        observed = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
        quote = average_first_20_offer_rate(offers, observed_at=observed)
        self.assertEqual(quote.rate, Decimal("0.25"))
        self.assertEqual(quote.observed_at, observed)

    def test_average_rejects_empty_offer_list(self):
        with self.assertRaisesRegex(ValueError, "no USDT/ECR offers"):
            average_first_20_offer_rate([], observed_at=datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc))

    def test_money_storage_polling_interval_is_15_minutes(self):
        self.assertEqual(MONEY_STORAGE_POLL_SECONDS, 900)
        self.assertEqual(MONEY_STORAGE_PAGE_SIZE, 20)


if __name__ == "__main__":
    unittest.main()


class MoneyStorageHttpProviderTests(unittest.TestCase):
    def test_requires_explicit_currency_filters_and_https(self):
        with self.assertRaisesRegex(ValueError, "filters are required"):
            MoneyStorageQuoteProvider(from_currency="", to_currency="USDT")
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            MoneyStorageQuoteProvider(
                from_currency="ECR", to_currency="USDT", endpoint="http://storage.money/public_deals/fetch"
            )

    def test_direct_http_provider_refuses_to_publish_without_page_timestamp(self):
        from unittest.mock import patch

        provider = MoneyStorageQuoteProvider(from_currency="ECR", to_currency="USDT")
        with patch("urllib.request.urlopen") as mocked:
            with self.assertRaisesRegex(RuntimeError, "cannot verify the page update timestamp"):
                provider.fetch_quote()
        mocked.assert_not_called()
