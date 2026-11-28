from __future__ import annotations

import unittest

from scripts.mark_profile_rotation_eligible import EXPECTED, validate_report


def valid_cookie_report():
    return {
        "all_pages_have_session_alive": True,
        "pages": {
            "money_storage": {"target_found": True, "session_alive_present": True},
            "sberkassa_deals": {"target_found": True, "session_alive_present": True},
            "sberkassa_exchange": {"target_found": True, "session_alive_present": True},
        },
    }


def valid_report():
    return {
        "overall_status": "ALL_THREE_COLLECTORS_SUCCESS",
        "sources": {
            "money_storage": {
                "status": "SUCCESS",
                "collector_status": EXPECTED["money_storage"],
                "artifact_status": "AVAILABLE",
                "quote": {"pair": "USDT/ECR", "freshness_confirmed": True},
            },
            "sberkassa_deals": {
                "status": "SUCCESS",
                "collector_status": EXPECTED["sberkassa_deals"],
                "artifact_status": "AVAILABLE",
                "quote": {"direction": "ERUB->RUB", "fresh": True},
            },
            "sberkassa_exchange": {
                "status": "SUCCESS",
                "collector_status": EXPECTED["sberkassa_exchange"],
                "artifact_status": "AVAILABLE",
                "quote": {
                    "selected_pair": {"from": "RUB", "to": "USDT"},
                    "displayed_rate": "0.0123",
                },
            },
        },
    }


class ProfileRotationEligibilityTests(unittest.TestCase):
    def test_all_three_validated_sources_are_eligible(self):
        eligible, reason = validate_report(valid_report(), valid_cookie_report())
        self.assertTrue(eligible)
        self.assertEqual(reason, "ALL_THREE_SOURCES_VALIDATED")

    def test_missing_session_alive_cookie_blocks_rotation(self):
        cookies = valid_cookie_report()
        cookies["pages"]["sberkassa_exchange"]["session_alive_present"] = False
        cookies["all_pages_have_session_alive"] = False
        eligible, reason = validate_report(valid_report(), cookies)
        self.assertFalse(eligible)
        self.assertEqual(reason, "SESSION_ALIVE_COOKIE_CHECK_FAILED")

    def test_partial_run_is_not_eligible(self):
        report = valid_report()
        report["overall_status"] = "PARTIAL_OR_FAILED"
        eligible, reason = validate_report(report, valid_cookie_report())
        self.assertFalse(eligible)
        self.assertEqual(reason, "OVERALL_STATUS_NOT_SUCCESS")

    def test_missing_source_artifact_is_not_eligible(self):
        report = valid_report()
        report["sources"]["sberkassa_deals"]["artifact_status"] = "ARTIFACT_MISSING"
        eligible, reason = validate_report(report, valid_cookie_report())
        self.assertFalse(eligible)
        self.assertEqual(reason, "SBERKASSA_DEALS_ARTIFACT_MISSING")

    def test_stale_money_storage_quote_is_not_eligible(self):
        report = valid_report()
        report["sources"]["money_storage"]["quote"]["freshness_confirmed"] = False
        eligible, reason = validate_report(report, valid_cookie_report())
        self.assertFalse(eligible)
        self.assertEqual(reason, "MONEY_STORAGE_QUOTE_NOT_VALIDATED")

    def test_unvalidated_sberkassa_deals_quote_is_not_eligible(self):
        report = valid_report()
        report["sources"]["sberkassa_deals"]["quote"]["fresh"] = False
        eligible, reason = validate_report(report, valid_cookie_report())
        self.assertFalse(eligible)
        self.assertEqual(reason, "SBERKASSA_DEALS_QUOTE_NOT_VALIDATED")

    def test_wrong_exchange_pair_is_not_eligible(self):
        report = valid_report()
        report["sources"]["sberkassa_exchange"]["quote"]["selected_pair"]["to"] = "EUR"
        eligible, reason = validate_report(report, valid_cookie_report())
        self.assertFalse(eligible)
        self.assertEqual(reason, "SBERKASSA_EXCHANGE_PAIR_NOT_VALIDATED")


if __name__ == "__main__":
    unittest.main()
