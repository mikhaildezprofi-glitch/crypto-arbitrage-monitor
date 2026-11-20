import unittest
from decimal import Decimal

from scripts.sberkassa_deals_rate import SberkassaQuoteError, calculate_erub_rub_average


class SberkassaDealsRateTests(unittest.TestCase):
    def test_averages_explicitly_selected_back_rate(self):
        offers = [
            {"rate": "0.038", "back_rate": "26", "create_time": 1},
            {"rate": "0.04", "back_rate": "25", "create_time": 999},
        ]
        result = calculate_erub_rub_average(offers, rate_field="back_rate")
        self.assertEqual(result["rate"], 25.5)
        self.assertEqual(result["rate_field"], "back_rate")
        self.assertEqual(result["offers_used"], 2)

    def test_averages_explicitly_selected_rate(self):
        offers = [{"rate": "10", "back_rate": "0.1"}, {"rate": "20", "back_rate": "0.05"}]
        result = calculate_erub_rub_average(offers, rate_field="rate")
        self.assertEqual(result["rate"], 15.0)

    def test_uses_first_twenty_in_original_order(self):
        offers = [{"rate": str(i + 1)} for i in range(25)]
        result = calculate_erub_rub_average(offers, rate_field="rate")
        self.assertEqual(result["offers_used"], 20)
        self.assertEqual(result["rate"], float(Decimal("10.5")))

    def test_averages_all_when_fewer_than_twenty(self):
        result = calculate_erub_rub_average([{"rate": "2"}, {"rate": "4"}], rate_field="rate")
        self.assertEqual(result["rate"], 3.0)

    def test_empty_offers_fail_closed(self):
        with self.assertRaises(SberkassaQuoteError):
            calculate_erub_rub_average([], rate_field="rate")

    def test_unknown_rate_field_fails_closed(self):
        with self.assertRaises(SberkassaQuoteError):
            calculate_erub_rub_average([{"rate": "2"}], rate_field="price")

    def test_invalid_selected_rate_fails_closed(self):
        with self.assertRaises(SberkassaQuoteError):
            calculate_erub_rub_average([{"rate": "2"}, {"rate": "NaN"}], rate_field="rate")

    def test_non_positive_rate_fails_closed(self):
        with self.assertRaises(SberkassaQuoteError):
            calculate_erub_rub_average([{"rate": "0"}], rate_field="rate")


if __name__ == "__main__":
    unittest.main()
