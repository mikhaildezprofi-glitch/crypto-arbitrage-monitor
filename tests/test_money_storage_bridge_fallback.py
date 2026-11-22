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

    def test_access_only_modes_never_fall_through_to_quote_reader(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "scripts" / "money_storage_chromium_bridge.py").read_text(encoding="utf-8")
        guard = source.index("if RETURN_ONLY or SESSION_CHECK:")
        capture_guard = source.index("if not SESSION_CHECK and not RETURN_ONLY:")
        capture_install = source.index('"Page.addScriptToEvaluateOnNewDocument"')
        self.assertLess(capture_guard, capture_install)
        offer_read = source.index("snapshot = fetch_from_authenticated_page(page)")
        self.assertLess(guard, offer_read)
        self.assertIn("time.sleep(2)", source[guard:offer_read])
        self.assertIn("continue", source[guard:offer_read])

    def test_return_only_logs_visible_currency_form_metadata(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "scripts" / "money_storage_chromium_bridge.py").read_text(encoding="utf-8")
        ast.parse(source)
        diagnostic = source.index("def deals_form_diagnostics")
        candidate = source.index('STATUS_FILE.write_text("MONEY_STORAGE_SESSION_CANDIDATE"')
        self.assertLess(diagnostic, candidate)
        self.assertIn('querySelectorAll("select, [role=combobox], input")', source)
        self.assertIn("selectedText", source)
        self.assertIn("selectedValue", source)
        self.assertNotIn("item.value = element.value", source)
        self.assertIn('print("PAGE_DIAG deals_form="', source)
        self.assertIn("currencyHint", source)
        self.assertIn("currencyControls", source)

    def test_unauthorized_deals_fallback_precedes_offer_page_read(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "scripts" / "money_storage_chromium_bridge.py").read_text(encoding="utf-8")
        fallback = source.index("MONEY_STORAGE_LOGIN_REQUIRED")
        offer_read = source.index("snapshot = fetch_from_authenticated_page(page)")
        self.assertLess(fallback, offer_read)


if __name__ == "__main__":
    unittest.main()
