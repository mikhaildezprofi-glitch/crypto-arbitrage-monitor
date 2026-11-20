import unittest
from decimal import Decimal

from scripts.sberkassa_deals_rate import SberkassaQuoteError, calculate_erub_rub_average


class SberkassaDealsRateTests(unittest.TestCase):
    def test_uses_rate_only_and_ignores_back_rate(self):
        payload = {"data": [
            {"rate": "10", "back_rate": "0.1", "create_time": 1},
            {"rate": "20", "back_rate": "0.05", "create_time": 999},
        ]}
        result = calculate_erub_rub_average(payload)
        self.assertEqual(result["rate"], 15.0)
        self.assertEqual(result["offers_used"], 2)
        self.assertFalse(result["back_rate_used"])

    def test_uses_first_twenty_in_original_order(self):
        payload = {"offers": [{"rate": str(i + 1), "back_rate": "999"} for i in range(25)]}
        result = calculate_erub_rub_average(payload)
        self.assertEqual(result["offers_used"], 20)
        self.assertEqual(result["rate"], float(Decimal("10.5")))

    def test_averages_all_when_fewer_than_twenty(self):
        result = calculate_erub_rub_average({"offers": [{"rate": "2"}, {"rate": "4"}]})
        self.assertEqual(result["rate"], 3.0)

    def test_empty_offers_fail_closed(self):
        with self.assertRaises(SberkassaQuoteError):
            calculate_erub_rub_average({"offers": []})

    def test_invalid_selected_rate_fails_closed(self):
        with self.assertRaises(SberkassaQuoteError):
            calculate_erub_rub_average({"offers": [{"rate": "2"}, {"rate": "NaN"}]})

    def test_non_positive_rate_fails_closed(self):
        with self.assertRaises(SberkassaQuoteError):
            calculate_erub_rub_average({"offers": [{"rate": "0"}]})


if __name__ == "__main__":
    unittest.main()
