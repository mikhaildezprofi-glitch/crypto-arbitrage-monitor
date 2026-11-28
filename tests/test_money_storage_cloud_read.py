import json
import os
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from arbitrage_monitor.providers.money_storage import parse_public_offer
from scripts.money_storage_cloud_read import (
    confirm_offer_freshness,
    latest_offer_created_at,
    fetch_from_authenticated_page,
    parse_authenticated_payload,
)


def raw_offer(created_at, rate="0.20"):
    return {
        "src_amount": "1000",
        "src_currency": "ECR",
        "dst_amount": "200",
        "dst_currency": "USDT",
        "rate": rate,
        "back_rate": "5",
        "commission": None,
        "commission_currency": None,
        "create_time": int(created_at.timestamp()),
    }


class MoneyStorageOfferFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)

    def test_browser_clock_must_match_cloud_runner_clock(self):
        class SkewedBrowserPage:
            url = "https://storage.money/deals#tab-3"

            def evaluate(self, script, argument=None):
                if script.strip() == "() => Date.now()":
                    return datetime.now(timezone.utc).timestamp() * 1000 + 10_000
                raise AssertionError("API request must not run when browser clock is skewed.")

        with self.assertRaisesRegex(RuntimeError, "clocks differ by more than 5 seconds"):
            fetch_from_authenticated_page(SkewedBrowserPage())

    def test_reader_reuses_page_captured_response_without_second_request(self):
        now = datetime.now(timezone.utc)
        payload = {
            "result": "ok",
            "data": [raw_offer(now - timedelta(minutes=2), "0.25")],
        }

        class CapturedOffersPage:
            url = "https://storage.money/deals#tab-3"

            def evaluate(self, script, argument=None):
                if script.strip() == "() => Date.now()":
                    return datetime.now(timezone.utc).timestamp() * 1000
                if "__moneyStorageOffersCapture" in script:
                    return {
                        "status": 200,
                        "finalUrl": "https://storage.money/public_deals/fetch?offset=0&limit=20&from=ECR&to=USDT",
                        "contentType": "application/json",
                        "text": json.dumps(payload),
                    }
                raise AssertionError("Reader must reuse captured page response, not issue another fetch.")

        with tempfile.TemporaryDirectory() as workspace:
            with patch.dict(os.environ, {"GITHUB_WORKSPACE": workspace}):
                snapshot = fetch_from_authenticated_page(CapturedOffersPage())
        self.assertEqual(snapshot["rate"], "0.25")
        self.assertTrue(snapshot["freshness_confirmed"])

    def test_reader_rejects_and_reports_non_get_quote_request(self):
        class NonGetCapturePage:
            url = "https://storage.money/deals#tab-3"

            def evaluate(self, script, argument=None):
                if script.strip() == "() => Date.now()":
                    return datetime.now(timezone.utc).timestamp() * 1000
                if "__moneyStorageOffersCaptures" in script:
                    return {
                        "blockedNonGet": True,
                        "method": "POST",
                        "requestUrl": "https://storage.money/public_deals/fetch?offset=0&limit=20&from=ECR&to=USDT",
                    }
                raise AssertionError("Unexpected browser evaluation.")

        with self.assertRaisesRegex(RuntimeError, "non-GET method POST; blocked by read-only policy"):
            fetch_from_authenticated_page(NonGetCapturePage())

    def test_reader_rejects_captured_response_with_wrong_offer_query(self):
        now = datetime.now(timezone.utc)
        payload = {
            "result": "ok",
            "data": [raw_offer(now - timedelta(minutes=2), "0.25")],
        }

        class WrongQueryPage:
            url = "https://storage.money/deals#tab-3"

            def evaluate(self, script, argument=None):
                if script.strip() == "() => Date.now()":
                    return datetime.now(timezone.utc).timestamp() * 1000
                if "__moneyStorageOffersCaptures" in script:
                    self.selection_script = script
                    return {
                        "status": 200,
                        "finalUrl": "https://storage.money/public_deals/fetch?offset=0&limit=20&from=USDT&to=ECR",
                        "contentType": "application/json",
                        "text": json.dumps(payload),
                    }
                raise AssertionError("Unexpected browser evaluation.")

        page = WrongQueryPage()
        with self.assertRaisesRegex(RuntimeError, "did not match the approved offers endpoint"):
            fetch_from_authenticated_page(page)
        self.assertIn('q.get("from") === "ECR"', page.selection_script)
        self.assertIn('q.get("to") === "USDT"', page.selection_script)
        self.assertIn('captures.find(item => item && (approved(item.finalUrl) || approved(item.requestUrl)))', page.selection_script)

    def test_newest_offer_within_15_minutes_confirms_freshness(self):
        offers = (
            parse_public_offer(raw_offer(self.now - timedelta(minutes=30))),
            parse_public_offer(raw_offer(self.now - timedelta(minutes=14))),
        )
        self.assertEqual(
            confirm_offer_freshness(offers, collected_at=self.now),
            self.now - timedelta(minutes=14),
        )

    def test_exactly_15_minutes_is_fresh(self):
        offers = (parse_public_offer(raw_offer(self.now - timedelta(minutes=15))),)
        self.assertEqual(confirm_offer_freshness(offers, collected_at=self.now), self.now - timedelta(minutes=15))

    def test_newest_offer_older_than_15_minutes_is_stale(self):
        offers = (
            parse_public_offer(raw_offer(self.now - timedelta(minutes=20))),
            parse_public_offer(raw_offer(self.now - timedelta(minutes=16))),
        )
        with self.assertRaisesRegex(ValueError, "older than the 900-second"):
            confirm_offer_freshness(offers, collected_at=self.now)

    def test_future_newest_offer_does_not_confirm_freshness(self):
        offers = (parse_public_offer(raw_offer(self.now + timedelta(seconds=1))),)
        with self.assertRaisesRegex(ValueError, "in the future"):
            confirm_offer_freshness(offers, collected_at=self.now)

    def test_empty_offer_list_does_not_confirm_freshness(self):
        with self.assertRaisesRegex(ValueError, "no offers"):
            confirm_offer_freshness([], collected_at=self.now)

    def test_payload_uses_collection_time_for_quote_and_newest_offer_for_freshness(self):
        created = self.now - timedelta(minutes=5)
        payload = {"result": "ok", "data": [raw_offer(created, "0.25"), raw_offer(created - timedelta(minutes=20), "0.35")]}
        snapshot = parse_authenticated_payload(payload, observed_at=self.now)
        self.assertEqual(snapshot["rate"], "0.30")
        self.assertEqual(snapshot["observed_at"], self.now.isoformat())
        self.assertEqual(snapshot["newest_offer_created_at"], created.isoformat())
        self.assertTrue(snapshot["freshness_confirmed"])
        self.assertEqual(snapshot["freshness_window_seconds"], 900)


if __name__ == "__main__":
    unittest.main()
