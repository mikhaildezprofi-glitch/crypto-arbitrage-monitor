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
        self.assertIn("sberkassa-current-inspection.json", source)
        self.assertIn("eid_provider_seen", source)
        # Read-only navigation is used only between the two approved quote pages.
        self.assertIn('"Runtime.evaluate"', source)
        auth_probe = source.split('auth_state = cdp.command(', 1)[1].split('auth_url = urlparse(auth_state.get("url", ""))', 1)[0]
        self.assertIn('"awaitPromise": True', auth_probe)
        self.assertIn('"Page.navigate"', source)
        self.assertIn('SBERKASSA_SESSION=RESTORED_PROFILE_REUSED', source)
        self.assertIn('SBERKASSA_AUTO_NAVIGATE=exchange', source)
        self.assertIn('session-authenticated.txt', source)
        self.assertIn('r"(rate|price|updated|timestamp|date|time)"', source)
        self.assertIn("currency_id|from_id|to_id", source)
        self.assertIn('"/exchange": "exchange_rub_usdt"', source)
        self.assertIn("if seen_deals and seen_exchange", source)
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

    def test_sberkassa_uses_money_storage_style_first_twenty_average(self):
        project_root = Path(__file__).resolve().parents[1]
        readme = (project_root / "README.md").read_text(encoding="utf-8")
        self.assertIn("arithmetic mean of the first 20 matching offers", readme)
        self.assertIn("Do not use commissions, offer amounts, volumes, reserves", readme)
        self.assertIn("single displayed rate without inventing an average", readme)

    def test_sberkassa_workflow_starts_from_its_own_login_page(self):
        project_root = Path(__file__).resolve().parents[1]
        workflow = (project_root / ".github" / "workflows" / "browserless-eid-handoff-stable.yml").read_text(encoding="utf-8")
        self.assertIn('CHROMIUM_START_URL="https://sberkassa.site/deals#tab-3"', workflow)
        self.assertIn("hashFiles('session-authenticated.txt')", workflow)
        self.assertIn("steps.encrypt-profile.outcome == 'success'", workflow)
        self.assertIn('BRIDGE_SCRIPT="scripts/sberkassa_chromium_probe.py"', workflow)
        self.assertIn('CHROMIUM_START_URL="https://storage.money/deals#tab-3"', workflow)
        self.assertIn('name: sberkassa-current-inspection', workflow)
        self.assertIn('path: sberkassa-current-inspection.json', workflow)


if __name__ == "__main__":
    unittest.main()
