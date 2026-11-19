import unittest
from datetime import datetime, timezone
from decimal import Decimal

from scripts.money_storage_cloud_read import parse_authenticated_payload


def row(rate, **overrides):
    data = {
        "src_amount": "1000", "src_currency": "ECR",
        "dst_amount": "3430", "dst_currency": "USDT",
        "rate": str(rate), "back_rate": "3.43",
        "commission": "17.15", "commission_currency": "USDT",
        "create_time": 1794843483,
    }
    data.update(overrides)
    return data


class MoneyStorageCloudReadTests(unittest.TestCase):
    def test_normalizes_only_everyone_offers_and_averages_first_twenty(self):
        payload = {"result": "ok", "data": [row(Decimal("0.2") + Decimal(i) / 100) for i in range(22)]}
        observed = datetime(2026, 11, 19, tzinfo=timezone.utc)
        result = parse_authenticated_payload(payload, observed)
        expected = sum((Decimal(str(Decimal("0.2") + Decimal(i) / 100)) for i in range(20)), Decimal("0")) / 20
        self.assertEqual(result["rate"], str(expected))
        self.assertEqual(result["offer_count"], 20)
        self.assertEqual(result["pair"], "USDT/ECR")
        self.assertFalse(result["commission_applied"])
        self.assertFalse(result["historical_data_saved"])

    def test_accepts_fewer_offers_and_rejects_empty_payload(self):
        result = parse_authenticated_payload({"result": "ok", "data": [row("0.2"), row("0.3")]})
        self.assertEqual(result["offer_count"], 2)
        self.assertEqual(result["rate"], "0.25")
        with self.assertRaisesRegex(ValueError, "no USDT/ECR offers"):
            parse_authenticated_payload({"result": "ok", "data": []})

    def test_rejects_wrong_envelope(self):
        with self.assertRaisesRegex(ValueError, "result=ok"):
            parse_authenticated_payload({"result": "error", "data": [row("0.2")]})


if __name__ == "__main__":
    unittest.main()
