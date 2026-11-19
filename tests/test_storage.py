import unittest
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from arbitrage_monitor.models import Quote, QuoteStatus
from arbitrage_monitor.storage import SQLiteQuoteStore


class SQLiteQuoteStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = SQLiteQuoteStore(":memory:")
        self.now = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)

    def tearDown(self):
        self.store.close()

    def quote(self, observed_at=None):
        return Quote(
            source="winance",
            pair="ERUB/USDT",
            base_currency="ERUB",
            quote_currency="USDT",
            rate=Decimal("0.04"),
            observed_at=observed_at or self.now,
            source_pair_id="18",
        )

    def test_persists_and_returns_fresh_quote(self):
        self.store.record_success(self.quote(), attempted_at=self.now)
        result = self.store.latest_fresh_quotes(
            max_age_seconds=900,
            now=self.now + timedelta(seconds=30),
        )
        self.assertEqual(result["winance"].rate, Decimal("0.04"))
        self.assertEqual(result["winance"].source_pair_id, "18")
        self.assertEqual(
            self.store.source_status()["winance"]["status"],
            QuoteStatus.FRESH.value,
        )

    def test_failed_poll_invalidates_previous_success(self):
        self.store.record_success(self.quote(), attempted_at=self.now)
        self.store.record_failure(
            "winance",
            TimeoutError("sensitive detail must not be stored"),
            attempted_at=self.now + timedelta(seconds=10),
        )
        result = self.store.latest_fresh_quotes(
            max_age_seconds=900,
            now=self.now + timedelta(seconds=20),
        )
        self.assertEqual(result, {})
        status = self.store.source_status()["winance"]
        self.assertEqual(status["status"], QuoteStatus.UNAVAILABLE.value)
        self.assertEqual(status["last_success_at"], self.now.isoformat())
        self.assertEqual(status["error_type"], "TimeoutError")
        self.assertNotIn("sensitive", str(status))

    def test_stale_quote_is_not_returned_and_status_changes(self):
        old = self.now - timedelta(seconds=901)
        self.store.record_success(self.quote(old), attempted_at=self.now)
        result = self.store.latest_fresh_quotes(
            max_age_seconds=900,
            now=self.now,
        )
        self.assertEqual(result, {})
        self.assertEqual(
            self.store.source_status()["winance"]["status"],
            QuoteStatus.STALE.value,
        )

    def test_future_quote_is_not_returned(self):
        future = self.now + timedelta(seconds=1)
        self.store.record_success(self.quote(future), attempted_at=self.now)
        result = self.store.latest_fresh_quotes(
            max_age_seconds=900,
            now=self.now,
        )
        self.assertEqual(result, {})

    def test_file_database_survives_store_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "quotes.sqlite3")
            first = SQLiteQuoteStore(database)
            first.record_success(self.quote(), attempted_at=self.now)
            first.close()

            reopened = SQLiteQuoteStore(database)
            try:
                result = reopened.latest_fresh_quotes(
                    max_age_seconds=900,
                    now=self.now + timedelta(seconds=30),
                )
                self.assertEqual(result["winance"].rate, Decimal("0.04"))
            finally:
                reopened.close()

    def test_poll_interval_uses_last_attempt_time(self):
        self.assertTrue(self.store.is_due("winance", 300, now=self.now))
        self.store.record_success(self.quote(), attempted_at=self.now)
        self.assertFalse(
            self.store.is_due(
                "winance", 300, now=self.now + timedelta(seconds=299)
            )
        )
        self.assertTrue(
            self.store.is_due(
                "winance", 300, now=self.now + timedelta(seconds=300)
            )
        )

    def test_negative_poll_interval_is_rejected(self):
        with self.assertRaises(ValueError):
            self.store.is_due("winance", -1, now=self.now)

    def test_negative_max_age_is_rejected(self):
        with self.assertRaises(ValueError):
            self.store.latest_fresh_quotes(max_age_seconds=-1, now=self.now)


if __name__ == "__main__":
    unittest.main()
