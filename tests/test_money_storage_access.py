import unittest

from arbitrage_monitor.providers.money_storage_access import (
    classify_cloudflare_challenge,
    classify_money_storage_page,
    is_money_storage_auth_failure,
)


class MoneyStoragePageClassificationTests(unittest.TestCase):
    def test_direct_deals_return_is_accepted(self):
        self.assertEqual(classify_money_storage_page("https://storage.money/deals#tab-3"), "deals")

    def test_account_return_is_a_valid_landing_route(self):
        self.assertEqual(classify_money_storage_page("https://storage.money/account"), "account")

    def test_provider_login_route_is_distinct_from_account(self):
        self.assertEqual(classify_money_storage_page("https://storage.money/login"), "login")

    def test_other_storage_route_can_be_navigated_to_deals_after_eid(self):
        self.assertEqual(classify_money_storage_page("https://storage.money/dashboard"), "other")

    def test_external_eid_route_is_not_mistaken_for_storage(self):
        self.assertEqual(classify_money_storage_page("https://e-id.cards/login"), "external")


class CloudflareChallengeClassificationTests(unittest.TestCase):
    def test_challenge_can_be_detected_before_eid(self):
        self.assertTrue(classify_cloudflare_challenge(
            host="storage.money", path="/deals",
            body="Checking your browser before accessing storage.money"
        ))

    def test_challenge_can_be_detected_after_eid_by_response_metadata(self):
        self.assertTrue(classify_cloudflare_challenge(
            host="storage.money", path="/deals", body="", response_challenge=True
        ))

    def test_challenge_platform_path_is_detected(self):
        self.assertTrue(classify_cloudflare_challenge(
            host="storage.money", path="/cdn-cgi/challenge-platform/h/g/orchestrate", body=""
        ))

    def test_turnstile_marker_is_detected(self):
        self.assertTrue(classify_cloudflare_challenge(
            host="storage.money", path="/deals", body='<div class="cf-turnstile"></div>'
        ))

    def test_cloudflare_branding_alone_is_not_a_challenge(self):
        self.assertFalse(classify_cloudflare_challenge(
            host="storage.money", path="/deals",
            body="Protected by Cloudflare. Site security and performance."
        ))

    def test_normal_offers_page_is_not_a_challenge(self):
        self.assertFalse(classify_cloudflare_challenge(
            host="storage.money", path="/deals", body="Everyone offers"
        ))


class MoneyStorageAuthenticationFailureTests(unittest.TestCase):
    def test_http_401_is_auth_failure(self):
        self.assertTrue(is_money_storage_auth_failure(status=401))

    def test_http_403_is_auth_failure(self):
        self.assertTrue(is_money_storage_auth_failure(status=403))

    def test_session_timeout_body_is_auth_failure_even_with_http_200(self):
        self.assertTrue(is_money_storage_auth_failure(
            status=200, title="Money Storage",
            body="Session timed out. You must log in to the main page."
        ))

    def test_normal_account_page_is_not_auth_failure(self):
        self.assertFalse(is_money_storage_auth_failure(
            status=200, title="Account", body="Account settings"
        ))

    def test_missing_status_and_normal_body_is_not_auth_failure(self):
        self.assertFalse(is_money_storage_auth_failure(status=None, title="", body=""))


if __name__ == "__main__":
    unittest.main()
