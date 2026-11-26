import unittest
from pathlib import Path


class FourStepRunnerSyntaxTests(unittest.TestCase):
    def test_runner_compiles_and_uses_only_four_sources(self):
        root = Path(__file__).resolve().parents[1]
        runner = root / "scripts" / "run_four_step_quote_test.py"
        source = runner.read_text(encoding="utf-8")
        compile(source, str(runner), "exec")
        self.assertIn("FOUR_STEP_PROVIDER_KEYS", source)
        self.assertIn("profit_calculated", source)
        self.assertIn("roi_calculated", source)
        self.assertIn('"fifth_source_requested": False', source)
        self.assertIn("MoneyStorageSnapshotQuoteProvider", source)
        self.assertIn("SberkassaSnapshotQuoteProvider", source)
        self.assertIn("BlackBitQuoteProvider", source)
        self.assertIn("WinanceQuoteProvider", source)

    def test_combined_workflow_keeps_provider_sessions_isolated(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github" / "workflows" / "four-step-quote-test.yml").read_text(encoding="utf-8")
        reusable = (root / ".github" / "workflows" / "browserless-eid-handoff-stable.yml").read_text(encoding="utf-8")
        self.assertIn("target: money_storage", workflow)
        self.assertIn("target: sberkassa", workflow)
        self.assertIn("secrets: inherit", workflow)
        self.assertIn("needs: [money-storage, sberkassa]", workflow)
        self.assertIn("    if: always()", workflow)
        self.assertIn("        continue-on-error: true", workflow)
        self.assertIn("MONEY_STORAGE_SNAPSHOT:", workflow)
        self.assertIn("SBERKASSA_SNAPSHOT:", workflow)
        self.assertIn("workflow_call:", reusable)
        self.assertIn("chromium-profile-money_storage-${{ github.ref_name }}-${{ inputs.target || 'manual' }}-", reusable)
        self.assertIn("  cancel-in-progress: false", reusable)
        self.assertIn("four-step-quote-test-${{ github.ref }}", workflow)
        self.assertIn("  cancel-in-progress: false", workflow)


    def test_full_collection_starts_all_three_provider_jobs_in_parallel(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github" / "workflows" / "full-read-only-collection.yml").read_text(encoding="utf-8")
        self.assertIn("target: [money_storage, sberkassa, sberkassa_exchange]", workflow)
        self.assertIn("target: ${{ matrix.target }}", workflow)
        self.assertIn("needs: browser", workflow)
        self.assertIn("parallel provider pages", workflow)



if __name__ == "__main__":
    unittest.main()
