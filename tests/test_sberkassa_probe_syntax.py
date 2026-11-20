import unittest
from pathlib import Path


class SberkassaProbeSyntaxTests(unittest.TestCase):
    def test_probe_script_compiles_without_importing_browser_dependencies(self):
        project_root = Path(__file__).resolve().parents[1]
        script_path = project_root / "scripts" / "sberkassa_chromium_probe.py"
        source = script_path.read_text(encoding="utf-8")
        compile(source, str(script_path), "exec")
        self.assertIn("MONEY_STORAGE_CALLBACK_CONFIRMED", source)
        self.assertIn('auth_host == "e-id.cards"', source)
        self.assertIn("eid_provider_seen", source)
        self.assertIn("Page.navigate", source)
        self.assertIn("https://sberkassa.site/login", source)
        self.assertIn('r"(rate|price|updated|timestamp|date|time)"', source)
        self.assertNotIn("volume|reserve|commission", source)

    def test_sberkassa_uses_money_storage_style_first_twenty_average(self):
        project_root = Path(__file__).resolve().parents[1]
        readme = (project_root / "README.md").read_text(encoding="utf-8")
        self.assertIn("arithmetic mean of the first 20 matching offers", readme)
        self.assertIn("Do not use commissions, offer amounts, volumes, reserves", readme)
        self.assertIn("single displayed rate without inventing an average", readme)

    def test_sberkassa_workflow_reuses_money_storage_eid_entry(self):
        project_root = Path(__file__).resolve().parents[1]
        workflow = (project_root / ".github" / "workflows" / "browserless-eid-handoff-stable.yml").read_text(encoding="utf-8")
        self.assertIn('CHROMIUM_START_URL="https://storage.money/account"', workflow)
        self.assertIn('BRIDGE_SCRIPT="scripts/sberkassa_chromium_probe.py"', workflow)


if __name__ == "__main__":
    unittest.main()
