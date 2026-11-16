import unittest
from decimal import Decimal

from arbitrage_monitor.providers.money_storage import (
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
        "rate": 0.29154519,
        "back_rate": 3.43,
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

    def test_extracts_only_target_direction_and_keeps_discrete_offers(self):
        payload = {
            "data": [
                raw_offer(),
                raw_offer(dst_amount="168.07", src_amount="49", create_time=1794843994),
                raw_offer(src_currency="USDT", dst_currency="ECR"),
            ]
        }
        offers = parse_public_offers(payload)
        self.assertEqual(len(offers), 2)
        self.assertEqual(offers[0].give_amount, Decimal("3430"))
        self.assertEqual(offers[1].give_amount, Decimal("168.07"))


    def test_rejects_empty_commission_currency(self):
        with self.assertRaisesRegex(ValueError, "must be supplied together"):
            parse_public_offer(raw_offer(commission="1", commission_currency=""))

    def test_selects_best_fresh_offer_that_fits_budget_without_combining(self):
        from datetime import datetime, timezone
        from arbitrage_monitor.providers.money_storage import select_best_affordable_offer

        now = datetime.fromtimestamp(1794843483, tz=timezone.utc)
        offers = parse_public_offers({
            "data": [
                raw_offer(dst_amount="3430", src_amount="1000", rate="0.29154519"),
                raw_offer(dst_amount="168.07", src_amount="49", rate="0.29154519"),
                raw_offer(dst_amount="900", src_amount="260", rate="0.28888889"),
            ]
        })
        selected = select_best_affordable_offer(
            offers, Decimal("1000"), max_age_seconds=900, now=now
        )
        # Same rate: newest timestamps are equal, so preserve more capital.
        self.assertEqual(selected.give_amount, Decimal("168.07"))
        self.assertEqual(selected.receive_amount, Decimal("49"))

    def test_rejects_when_no_single_offer_fits_budget(self):
        from datetime import datetime, timezone
        from arbitrage_monitor.providers.money_storage import select_best_affordable_offer

        offers = parse_public_offers({"data": [raw_offer(dst_amount="3430")]})
        with self.assertRaisesRegex(ValueError, "No fresh, discrete"):
            select_best_affordable_offer(
                offers,
                Decimal("1000"),
                now=datetime.fromtimestamp(1794843483, tz=timezone.utc),
            )

    def test_does_not_select_stale_or_future_offers(self):
        from datetime import datetime, timezone
        from arbitrage_monitor.providers.money_storage import select_best_affordable_offer

        offers = parse_public_offers({
            "data": [
                raw_offer(create_time=1794840000),
                raw_offer(create_time=1794845000, dst_amount="100"),
            ]
        })
        with self.assertRaisesRegex(ValueError, "No fresh, discrete"):
            select_best_affordable_offer(
                offers,
                Decimal("1000"),
                max_age_seconds=900,
                now=datetime.fromtimestamp(1794843483, tz=timezone.utc),
            )

    def test_parses_multiple_pages_without_deduplicating_offers(self):
        first = {"data": [raw_offer()]}
        second = {"data": [raw_offer()]}
        offers = parse_public_offer_pages([first, second])
        self.assertEqual(len(offers), 2)
        self.assertEqual(offers[0].give_amount, offers[1].give_amount)
        self.assertEqual(offers[0].created_at, offers[1].created_at)


if __name__ == "__main__":
    unittest.main()
