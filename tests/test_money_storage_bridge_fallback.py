import ast
import unittest
from pathlib import Path


class MoneyStorageBridgeFallbackTests(unittest.TestCase):
    def test_bridge_compiles_and_checks_document_status_before_quote_read(self):
        root = Path(__file__).resolve().parents[1]
        bridge = root / "scripts" / "money_storage_chromium_bridge.py"
        source = bridge.read_text(encoding="utf-8")
        ast.parse(source, filename=str(bridge))

        self.assertIn('cdp.command("Network.enable")', source)
        self.assertIn('cdp.command("Page.reload", {"ignoreCache": True})', source)
        self.assertIn("self.storage_document_status", source)
        self.assertIn("self.storage_document_path", source)
        self.assertIn("cdp.storage_document_status in (401, 403)", source)
        self.assertIn('cdp.command("Page.navigate", {"url": "https://storage.money/account"})', source)
        self.assertIn("MONEY_STORAGE_LOGIN_REQUIRED", source)


    def test_bridge_has_bounded_noninteractive_restored_session_mode(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "scripts" / "money_storage_chromium_bridge.py").read_text(encoding="utf-8")
        self.assertIn('SESSION_CHECK = os.environ.get("MONEY_STORAGE_SESSION_CHECK") == "1"', source)
        self.assertIn("DEADLINE_SECONDS = 180 if SESSION_CHECK else 1800", source)
        self.assertIn('STATUS_FILE.write_text("AUTH_REQUIRED"', source)
        self.assertIn('final_status = "SESSION_CHECK_TIMEOUT" if SESSION_CHECK else "MONEY_STORAGE_RETURN_TIMEOUT"', source)

    def test_unauthorized_deals_fallback_precedes_offer_page_read(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "scripts" / "money_storage_chromium_bridge.py").read_text(encoding="utf-8")
        fallback = source.index("MONEY_STORAGE_LOGIN_REQUIRED")
        offer_read = source.index("snapshot = fetch_from_authenticated_page(page)")
        self.assertLess(fallback, offer_read)


if __name__ == "__main__":
    unittest.main()
