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


if __name__ == "__main__":
    unittest.main()
