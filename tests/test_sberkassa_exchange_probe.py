import unittest
from pathlib import Path


class SberkassaExchangeProbeTests(unittest.TestCase):
    def test_probe_compiles_and_uses_real_browser_pointer_selection(self):
        root = Path(__file__).resolve().parents[1]
        path = root / "scripts" / "sberkassa_exchange_chromium_probe.py"
        source = path.read_text(encoding="utf-8")
        compile(source, str(path), "exec")
        self.assertIn('TARGET_URL = "https://sberkassa.site/exchange"', source)
        self.assertIn("selection_method", source)
        self.assertIn('"chromium_cdp_pointer_clicks"', source)
        self.assertIn("Input.dispatchMouseEvent", source)
        self.assertIn("mousePressed", source)
        self.assertIn("mouseReleased", source)
        self.assertIn("#currency_fromSelectBoxIt", source)
        self.assertIn("#currency_toSelectBoxIt", source)
        self.assertIn("#currency_' + dir + 'SelectBoxItOptions", source)
        self.assertIn('select_currency("from", "RUB")', source)
        self.assertIn('select_currency("to", "USDT")', source)
        self.assertIn("currency_code(label) == wanted", source)
        self.assertIn("#current_rate", source)
        self.assertIn("SBERKASSA_EXCHANGE_AUTOMATIC_PAIR_CONFIRMED=RUB_USDT", source)
        self.assertIn("SBERKASSA_EXCHANGE_RESULT_RECEIVED=YES", source)
        self.assertIn("SBERKASSA_EXCHANGE_RATE_CAPTURE_MODE=SINGLE_DISPLAYED_RATE", source)
        self.assertIn('"rate_capture_mode": "single_displayed_rate"', source)
        self.assertIn('selection_deadline = time.monotonic() + 300', source)
        self.assertIn('"exchange_submit_clicked": False', source)
        self.assertIn('"sell_amount_entered": False', source)
        self.assertIn('verb == "GET"', source)
        self.assertIn('"Fetch.failRequest"', source)
        self.assertIn('"Network.setCacheDisabled"', source)
        self.assertIn("sberkassa-exchange-inspection.json", source)
        self.assertNotIn("MANUAL_SELECTION_REQUIRED", source)
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
        self.assertIn("SBERKASSA_EXCHANGE_SELECTION_TIMEOUT", workflow)
        self.assertIn("timeout-minutes: 40", workflow)
        self.assertIn("timeout-minutes: 35", workflow)
        self.assertIn("seq 1 900", workflow)
        self.assertIn("inputs.target != ''", workflow)
        self.assertIn('BRIDGE_SCRIPT="scripts/sberkassa_chromium_probe.py"', workflow)


if __name__ == "__main__":
    unittest.main()
