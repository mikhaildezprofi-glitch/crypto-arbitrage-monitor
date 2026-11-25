import unittest
from pathlib import Path


class SberkassaExchangeProbeTests(unittest.TestCase):
    def test_probe_compiles_and_is_read_only(self):
        root = Path(__file__).resolve().parents[1]
        path = root / "scripts" / "sberkassa_exchange_chromium_probe.py"
        source = path.read_text(encoding="utf-8")
        compile(source, str(path), "exec")
        self.assertIn('TARGET_URL = "https://sberkassa.site/exchange"', source)
        self.assertIn("targets[0] if targets else None", source)
        self.assertIn('verb == "GET"', source)
        self.assertIn('"Fetch.failRequest"', source)
        self.assertIn('"Network.setCacheDisabled"', source)
        self.assertIn("sberkassa-exchange-inspection.json", source)
        self.assertIn("No page controls were clicked or changed", source)
        self.assertNotIn("Page.handleJavaScriptDialog", source)
        self.assertNotIn("Input.dispatchMouseEvent", source)
        self.assertNotIn("Input.insertText", source)
        self.assertNotIn("Network.getAllCookies", source)
        self.assertNotIn("Storage.getCookies", source)

    def test_workflow_has_separate_exchange_target_and_artifact(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github" / "workflows" / "browserless-eid-handoff-stable.yml").read_text(encoding="utf-8")
        self.assertIn("- sberkassa_exchange", workflow)
        self.assertIn('BRIDGE_SCRIPT="scripts/sberkassa_exchange_chromium_probe.py"', workflow)
        self.assertIn("name: sberkassa-exchange-inspection", workflow)
        self.assertIn("path: sberkassa-exchange-inspection.json", workflow)
        self.assertIn("SBERKASSA_EXCHANGE_INSPECTION_COMPLETE", workflow)
        self.assertIn("SBERKASSA_EXCHANGE_AUTH_TIMEOUT", workflow)
        self.assertIn("inputs.target != ''", workflow)
        self.assertIn('BRIDGE_SCRIPT="scripts/sberkassa_chromium_probe.py"', workflow)


if __name__ == "__main__":
    unittest.main()
