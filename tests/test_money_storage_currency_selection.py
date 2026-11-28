import ast
import unittest
from pathlib import Path


class MoneyStorageCurrencySelectionTests(unittest.TestCase):
    def test_bridge_compiles_and_uses_native_tom_select_values(self):
        root = Path(__file__).resolve().parents[1]
        path = root / "scripts" / "money_storage_chromium_bridge.py"
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path))

        self.assertIn('findSelect("select_from")', source)
        self.assertIn('findSelect("select_to")', source)
        self.assertIn("from.tomselect", source)
        self.assertIn("to.tomselect", source)
        self.assertIn('fromControl.setValue("ECR", true)', source)
        self.assertIn('toControl.setValue("USDT")', source)
        self.assertIn('selectedFrom === "ECR" && selectedTo === "USDT"', source)
        self.assertIn('controlFrom === "ECR" && controlTo === "USDT"', source)

    def test_pair_selection_runs_before_the_authenticated_offers_reader(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "scripts" / "money_storage_chromium_bridge.py").read_text(encoding="utf-8")
        select_at = source.index("select_approved_currency_pair(cdp)")
        read_at = source.index("snapshot = fetch_from_authenticated_page(page)")
        self.assertLess(select_at, read_at)

    def test_selection_failure_is_fail_closed(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "scripts" / "money_storage_chromium_bridge.py").read_text(encoding="utf-8")
        self.assertIn("Money Storage currency selection failed closed", source)
        self.assertIn("tom_select_instance_missing", source)
        self.assertIn("required_currency_option_missing", source)
        self.assertIn("selection_verification_failed", source)


if __name__ == "__main__":
    unittest.main()
