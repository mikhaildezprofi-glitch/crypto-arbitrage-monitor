from __future__ import annotations

import unittest

from scripts.shared_browser_auth_probe import classify


class SharedBrowserAuthProbeTests(unittest.TestCase):
    def state(self, **overrides):
        value = {
            "url": "https://storage.money/deals#tab-3",
            "ready": "complete",
            "titlePresent": True,
            "bodyLength": 120,
            "responseStatus": 200,
            "explicitAuthFailure": False,
            "visiblePasswordFieldCount": 0,
            "visibleLoginFormCount": 0,
            "moneyCurrencyFormReady": False,
            "sberkassaContentMarker": False,
            "challenge": False,
        }
        value.update(overrides)
        return value

    def test_money_storage_positive_dom_overrides_stale_401_navigation(self):
        state = self.state(responseStatus=401, moneyCurrencyFormReady=True)
        self.assertEqual(classify(("storage.money", "/deals"), state), "AUTHENTICATED")

    def test_money_storage_without_positive_dom_does_not_accept_401(self):
        state = self.state(responseStatus=401)
        self.assertEqual(classify(("storage.money", "/deals"), state), "HTTP_STATUS_UNCONFIRMED")

    def test_money_storage_explicit_expiry_overrides_positive_form(self):
        state = self.state(
            responseStatus=401,
            moneyCurrencyFormReady=True,
            explicitAuthFailure=True,
        )
        self.assertEqual(classify(("storage.money", "/deals"), state), "LOGIN_REQUIRED")

    def test_sberkassa_positive_page_dom_overrides_stale_403(self):
        state = self.state(
            url="https://sberkassa.site/deals#tab-3",
            responseStatus=403,
            bodyLength=240,
            sberkassaContentMarker=True,
        )
        self.assertEqual(classify(("sberkassa.site", "/deals"), state), "AUTHENTICATED")

    def test_sberkassa_visible_login_form_is_not_authenticated(self):
        state = self.state(
            url="https://sberkassa.site/exchange",
            bodyLength=240,
            sberkassaContentMarker=True,
            visibleLoginFormCount=1,
        )
        self.assertEqual(classify(("sberkassa.site", "/exchange"), state), "LOGIN_REQUIRED")

    def test_challenge_takes_precedence(self):
        state = self.state(challenge=True, moneyCurrencyFormReady=True)
        self.assertEqual(classify(("storage.money", "/deals"), state), "CHALLENGE_PENDING")

    def test_eid_redirect_is_reported_as_handoff(self):
        state = self.state(url="https://e-id.cards/identity/check")
        self.assertEqual(classify(("storage.money", "/deals"), state), "EID_HANDOFF_IN_PROGRESS")


if __name__ == "__main__":
    unittest.main()
