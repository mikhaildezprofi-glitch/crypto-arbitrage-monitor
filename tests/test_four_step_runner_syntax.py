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
        self.assertIn("four-step-quote-test-${{ github.ref }}", workflow)
        self.assertIn("  cancel-in-progress: false", workflow)


    def test_full_collection_uses_one_chromium_process_with_three_tabs(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github" / "workflows" / "full-read-only-collection.yml").read_text(encoding="utf-8")
        reusable = (root / ".github" / "workflows" / "browserless-eid-handoff-stable.yml").read_text(encoding="utf-8")
        browser_script = (root / "scripts" / "keep_browser_and_tunnel_alive.sh").read_text(encoding="utf-8")
        reusable += "\n" + browser_script
        self.assertIn("target: all", workflow)
        self.assertIn("needs: [shared-authenticated-browser]", workflow)
        self.assertIn("one shared Chromium, three tabs", workflow)
        self.assertIn('EXTRA_START_URLS=("https://sberkassa.site/deals#tab-3" "https://sberkassa.site/exchange")', reusable)
        self.assertIn("CHROMIUM_SINGLE_PROCESS=YES", reusable)
        self.assertIn("SHARED_CHROMIUM_THREE_TARGET_TABS=VERIFIED", reusable)
        self.assertIn("MONEY_STORAGE_STATUS_FILE=/tmp/money-storage-status", reusable)
        self.assertIn("SBERKASSA_STATUS_FILE=/tmp/sberkassa-sell-status", reusable)
        self.assertIn("SBERKASSA_EXCHANGE_STATUS_FILE=/tmp/sberkassa-exchange-status", reusable)
        self.assertIn("ALL_THREE_SHARED_BROWSER_TABS_COMPLETE=YES", reusable)


    def test_authenticated_profile_cache_uses_attempt_unique_key_and_auth_marker(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github" / "workflows" / "browserless-eid-handoff-stable.yml").read_text(encoding="utf-8")
        attempt_key = "${{ github.run_id }}-${{ github.run_attempt }}"
        self.assertEqual(workflow.count(attempt_key), 3)
        self.assertIn("hashFiles('shared-session-authenticated-tabs.txt') != ''", workflow)
        self.assertNotIn("hashFiles('auth-collection-complete.txt') != ''", workflow)
        self.assertIn("CHROMIUM_PROFILE_ARCHIVE_VALIDATED=YES", workflow)
        self.assertIn("CHROMIUM_SESSION_RESTORE_DATA_MISSING", workflow)
        self.assertIn("ALL_THREE_TABS_AUTHENTICATED", workflow)
        self.assertNotIn("hashFiles('money-storage-profile-ready.txt')", workflow)
        self.assertIn("for attempt in 1; do", workflow)
        self.assertIn("SESSION_CHECK_RESULT=1_OF_1_SUCCESS", workflow)



if __name__ == "__main__":
    unittest.main()
