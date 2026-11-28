from __future__ import annotations

import unittest

from scripts.mark_profile_rotation_eligible import validate_profile_eligibility


def valid_auth_marker():
    return chr(10).join(("money_storage", "sberkassa_deals", "sberkassa_exchange", ""))


def valid_cookie_report():
    return {
        "all_pages_have_session_alive": True,
        "pages": {
            "money_storage": {"cookie_database_count": 1, "session_alive_present": True},
            "sberkassa_deals": {"cookie_database_count": 1, "session_alive_present": True},
            "sberkassa_exchange": {"cookie_database_count": 1, "session_alive_present": True},
        },
    }


class ProfileRotationEligibilityTests(unittest.TestCase):
    def test_all_three_authenticated_tabs_and_cookies_are_eligible(self):
        eligible, reason = validate_profile_eligibility(valid_auth_marker(), valid_cookie_report())
        self.assertTrue(eligible)
        self.assertEqual(
            reason,
            "ALL_THREE_TABS_AUTHENTICATED_AND_SESSION_COOKIES_PRESENT",
        )

    def test_missing_tab_authentication_blocks_rotation(self):
        marker = chr(10).join(("money_storage", "sberkassa_deals", ""))
        eligible, reason = validate_profile_eligibility(marker, valid_cookie_report())
        self.assertFalse(eligible)
        self.assertEqual(reason, "THREE_TAB_AUTHENTICATION_NOT_CONFIRMED")

    def test_missing_session_alive_cookie_blocks_rotation(self):
        cookies = valid_cookie_report()
        cookies["pages"]["sberkassa_exchange"]["session_alive_present"] = False
        cookies["all_pages_have_session_alive"] = False
        eligible, reason = validate_profile_eligibility(valid_auth_marker(), cookies)
        self.assertFalse(eligible)
        self.assertEqual(reason, "SESSION_ALIVE_COOKIE_CHECK_FAILED")

    def test_missing_cookie_report_blocks_rotation(self):
        eligible, reason = validate_profile_eligibility(valid_auth_marker(), None)
        self.assertFalse(eligible)
        self.assertEqual(reason, "SESSION_ALIVE_COOKIE_CHECK_FAILED")


if __name__ == "__main__":
    unittest.main()
