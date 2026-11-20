import sys
import unittest
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.money_storage_cloud_read import parse_page_update_timestamp


class MoneyStoragePageTimestampTests(unittest.TestCase):
    def setUp(self):
        self.browser_now = {
            "year": 2026, "month": 11, "day": 20,
            "hour": 15, "minute": 30, "second": 0,
        }

    def test_parses_visible_full_timestamp_as_page_time(self):
        timestamp, source_line = parse_page_update_timestamp(
            ["Курс обновлён: 20.11.2026 15:21:13"],
            timezone_name="UTC",
            browser_local_now=self.browser_now,
        )
        self.assertEqual(timestamp, datetime(2026, 11, 20, 15, 21, 13, tzinfo=timezone.utc))
        self.assertEqual(source_line, "Курс обновлён: 20.11.2026 15:21:13")

    def test_parses_relative_page_update_time(self):
        timestamp, _ = parse_page_update_timestamp(
            ["Обновлено 3 минуты назад"],
            timezone_name="UTC",
            browser_local_now=self.browser_now,
        )
        self.assertEqual(timestamp, datetime(2026, 11, 20, 15, 27, tzinfo=timezone.utc))

    def test_parses_time_only_using_browser_timezone_and_date(self):
        timestamp, _ = parse_page_update_timestamp(
            ["Последнее обновление: 15:20"],
            timezone_name="UTC",
            browser_local_now=self.browser_now,
        )
        self.assertEqual(timestamp, datetime(2026, 11, 20, 15, 20, tzinfo=timezone.utc))

    def test_fails_closed_without_a_page_update_marker(self):
        with self.assertRaisesRegex(ValueError, "did not expose a parseable update timestamp"):
            parse_page_update_timestamp(
                ["Открыто", "20 предложений"],
                timezone_name="UTC",
                browser_local_now=self.browser_now,
            )


if __name__ == "__main__":
    unittest.main()
