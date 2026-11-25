import unittest
from pathlib import Path


class SberkassaProbeSyntaxTests(unittest.TestCase):
    def test_probe_script_compiles_without_importing_browser_dependencies(self):
        project_root = Path(__file__).resolve().parents[1]
        script_path = project_root / "scripts" / "sberkassa_chromium_probe.py"
        source = script_path.read_text(encoding="utf-8")
        compile(source, str(script_path), "exec")
        self.assertIn("SBERKASSA_CALLBACK_CONFIRMED", source)
        self.assertIn('auth_host == "e-id.cards"', source)
        self.assertIn('auth_host == "sberkassa.site"', source)
        self.assertNotIn('auth_url.path.rstrip("/") == "/login"', source)
        self.assertIn("extract_erub_rub_offer_records", source)
        self.assertIn("from scripts.money_storage_cloud_read import parse_page_update_timestamp", source)
        cloud_read = (project_root / "scripts" / "money_storage_cloud_read.py").read_text(encoding="utf-8")
        self.assertIn("def parse_page_update_timestamp(", cloud_read)
        self.assertIn('"offer_records": []', source)
        self.assertIn('"offer_request": {}', source)
        self.assertIn('safe_query.get("from") == "ERUB"', source)
        self.assertIn('safe_query.get("to") == "RUB"', source)
        self.assertIn('"SBERKASSA_ERUB_RUB_OFFERS captured=%s status=%s"', source)
        self.assertIn("sberkassa-current-inspection.json", source)
        self.assertIn("eid_provider_seen", source)
        # The Sberkassa collector remains on the approved deals tab only.
        self.assertIn('"Runtime.evaluate"', source)
        auth_probe = source.split('auth_state = cdp.command(', 1)[1].split('auth_url = urlparse(auth_state.get("url", ""))', 1)[0]
        self.assertIn('"awaitPromise": True', auth_probe)
        capture_probe = source.split('state = cdp.command(', 1)[1].split('url = state.get("url", "")', 1)[0]
        self.assertIn('"expression": """(async () => ({', capture_probe)
        self.assertIn('sourceInventory: await (async () => {', capture_probe)
        self.assertIn('"awaitPromise": True', capture_probe)
        self.assertIn('"Page.navigate"', source)
        self.assertIn('cdp.current_path = "/deals"', source)
        self.assertIn('"Fetch.enable"', source)
        self.assertIn('"Network.setCacheDisabled"', source)
        self.assertIn('"Page.addScriptToEvaluateOnNewDocument"', source)
        self.assertIn("localStorage.setItem('currency_from', 'ERUB')", source)
        self.assertIn("localStorage.setItem('currency_to', 'RUB')", source)
        self.assertIn('"https://sberkassa.site/deals#tab-3"', source)
        self.assertIn("len(records) < 20", source)
        self.assertIn("SBERKASSA_ERUB_RUB_VALIDATED", source)
        self.assertIn("SBERKASSA_SESSION=RESTORED_PROFILE_REUSED", source)
        self.assertNotIn("SBERKASSA_AUTO_NAVIGATE=exchange", source)
        self.assertIn("money-storage-profile-ready.txt", source)
        self.assertIn("CHROMIUM_PROFILE_PERSISTENCE=ELIGIBLE_AFTER_SBERKASSA_AUTH", source)
        self.assertIn("session-authenticated.txt", source)
        self.assertIn('r"(rate|price|updated|timestamp|date|time)"', source)
        self.assertIn("currency_id|from_id|to_id", source)
        self.assertIn('"Fetch.requestPaused"', source)
        self.assertIn('"Fetch.failRequest"', source)
        self.assertIn('query.get("from", [""])[0] != "ERUB"', source)
        self.assertIn('query.get("to", [""])[0] != "RUB"', source)
        self.assertIn("SBERKASSA_SCOPE_BLOCKED", source)
        self.assertNotIn("is_exchange", source)
        self.assertNotIn("exchange_rub_usdt", source)
        self.assertIn("if seen_deals and deals_ready_since is not None", source)
        self.assertIn("quoteLines:", source)
        self.assertIn('"visible_quote_lines"', source)
        self.assertIn("quoteDom:", source)
        self.assertIn('"visible_quote_dom"', source)
        self.assertIn("rate_inputs", source)
        self.assertIn("selectedOptions", source)
        self.assertIn("exchange_rate|buy_rate|sell_rate", source)
        # Broad but sanitized source discovery: DOM attributes, embedded state,
        # XHR/fetch JSON, WebSocket/EventSource frames and cache/response timing.
        self.assertIn("sourceInventory:", source)
        self.assertIn("embedded-json-", source)
        self.assertIn("Network.webSocketFrameReceived", source)
        self.assertIn("Network.eventSourceMessageReceived", source)
        self.assertIn("stream_quote_fields", source)
        self.assertIn("request_timing", source)
        self.assertIn("from_service_worker", source)
        self.assertIn('"localStorage", "sessionStorage"', source)
        self.assertIn("caches.keys()", source)
        self.assertIn("indexedDB.databases()", source)
        self.assertIn("getAll(undefined, 20)", source)
        self.assertNotIn("volume|reserve|commission", source)

    def test_sberkassa_uses_the_agreed_independent_freshness_and_average_rules(self):
        project_root = Path(__file__).resolve().parents[1]
        readme = (project_root / "README.md").read_text(encoding="utf-8")
        self.assertIn("at least one correctly directed offer", readme)
        self.assertIn("15 minutes before collection", readme)
        self.assertIn("regardless of their creation times", readme)
        self.assertIn("arithmetic mean of `back_rate`", readme)
        self.assertIn("ignore `rate` completely", readme)
        self.assertIn("single rate", readme)

    def test_sberkassa_workflow_starts_from_its_own_login_page(self):
        project_root = Path(__file__).resolve().parents[1]
        workflow = (project_root / ".github" / "workflows" / "browserless-eid-handoff-stable.yml").read_text(encoding="utf-8")
        self.assertIn('CHROMIUM_START_URL="about:blank"', workflow)
        self.assertIn("hashFiles('money-storage-profile-ready.txt')", workflow)
        self.assertIn("steps.encrypt-profile.outcome == 'success'", workflow)
        self.assertIn('BRIDGE_SCRIPT="scripts/sberkassa_chromium_probe.py"', workflow)
        self.assertIn('CHROMIUM_START_URL="https://storage.money/deals#tab-3"', workflow)
        self.assertIn('name: sberkassa-current-inspection', workflow)
        self.assertIn('path: sberkassa-current-inspection.json', workflow)


if __name__ == "__main__":
    unittest.main()
