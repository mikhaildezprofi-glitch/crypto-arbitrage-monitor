import unittest
from pathlib import Path


class SberkassaExchangeProbeTests(unittest.TestCase):
    def test_probe_compiles_and_automatically_selects_only_currency_dropdowns(self):
        root = Path(__file__).resolve().parents[1]
        path = root / "scripts" / "sberkassa_exchange_chromium_probe.py"
        source = path.read_text(encoding="utf-8")
        compile(source, str(path), "exec")
        self.assertIn('TARGET_URL = "https://sberkassa.site/exchange"', source)
        self.assertIn("const chooseByClick = (dir, wantedCode) =>", source)
        self.assertIn("chooseByClick('from', 'RUB')", source)
        self.assertIn("chooseByClick('to', 'USDT')", source)
        self.assertIn("const fromConfirmed = codeFromLabel(selectedLabel('from')) === 'RUB';", source)
        self.assertIn("waiting_for_from_selection", source)
        self.assertIn("const codeFromLabel = value =>", source)
        self.assertIn(r"/\\bUSDT\\b|TETHER|ТЕЗЕР/", source)
        self.assertIn(r"/\\bERUB\\b|E-RUBLE|Е-РУБЛ/", source)
        self.assertIn("selection_method", source)
        self.assertIn('"selection_confirmed": False', source)
        self.assertIn('pair.get("from") == "RUB"', source)
        self.assertIn('pair.get("to") == "USDT"', source)
        self.assertIn("SBERKASSA_EXCHANGE_AUTOMATIC_PAIR_CONFIRMED=RUB_USDT", source)
        self.assertIn("SBERKASSA_EXCHANGE_RESULT_RECEIVED=YES", source)
        self.assertIn("SBERKASSA_EXCHANGE_RATE_CAPTURE_MODE=SINGLE_DISPLAYED_RATE", source)
        self.assertIn('"rate_capture_mode": "single_displayed_rate"', source)
        selection_loop = source.split("selection_deadline = time.monotonic() + 300", 1)[1].split(
            'if selection.get("selection_confirmed") is not True:', 1
        )[0]
        self.assertNotIn("probe.drain_bodies()", selection_loop)
        self.assertIn("selection_deadline = time.monotonic() + 300", source)
        self.assertIn('"latest_dom_selection": ({', source)
        self.assertIn('samples[-1]["dom"].get("displayed_rate_text", "")', source)
        self.assertIn('"exchange_submit_clicked": False', source)
        self.assertIn('"sell_amount_entered": False', source)
        self.assertIn('verb == "GET"', source)
        self.assertIn('"Fetch.failRequest"', source)
        self.assertIn('"Network.setCacheDisabled"', source)
        self.assertIn("sberkassa-exchange-inspection.json", source)
        self.assertNotIn("MANUAL_SELECTION_REQUIRED", source)
        self.assertNotIn("manual currency selection", source.lower())
        self.assertNotIn("Input.dispatchMouseEvent", source)
        self.assertNotIn("Input.insertText", source)
        self.assertNotIn("Network.getAllCookies", source)
        self.assertNotIn("Storage.getCookies", source)

    def test_workflow_restores_original_time_limits_and_stops_on_result(self):
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
        self.assertNotIn("timeout-minutes: 65", workflow)
        self.assertNotIn("timeout-minutes: 60", workflow)
        self.assertNotIn("seq 1 1750", workflow)
        self.assertIn("inputs.target != ''", workflow)
        self.assertIn('BRIDGE_SCRIPT="scripts/sberkassa_chromium_probe.py"', workflow)


if __name__ == "__main__":
    unittest.main()
