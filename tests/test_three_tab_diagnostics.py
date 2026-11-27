import json
import tempfile
import unittest
from pathlib import Path

from scripts import build_three_tab_diagnostics as diagnostics


class ThreeTabDiagnosticsTests(unittest.TestCase):
    def test_report_marks_missing_sources_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = diagnostics.SOURCES
            try:
                diagnostics.SOURCES = {
                    "money_storage": {
                        "status_file": root / "missing-status",
                        "log_file": root / "missing.log",
                        "expected_status": "OFFERS_READ_OK",
                        "artifact": root / "missing.json",
                        "log_pattern": diagnostics.re.compile(r"^OFFERS_READ_"),
                    }
                }
                report = diagnostics.build(root / "out")
                self.assertEqual(report["overall_status"], "PARTIAL_OR_FAILED")
                source = report["sources"]["money_storage"]
                self.assertEqual(source["collector_status"], "STATUS_FILE_MISSING")
                self.assertEqual(source["artifact_status"], "ARTIFACT_MISSING")
            finally:
                diagnostics.SOURCES = original

    def test_collector_mode_is_noninteractive_and_does_not_reauthenticate(self):
        root = Path(__file__).resolve().parents[1]
        browser = (root / "scripts" / "keep_browser_and_tunnel_alive.sh").read_text(encoding="utf-8")
        exchange = (root / "scripts" / "sberkassa_exchange_chromium_probe.py").read_text(encoding="utf-8")
        reusable = (root / ".github" / "workflows" / "browserless-eid-handoff-stable.yml").read_text(encoding="utf-8")
        self.assertIn("MONEY_STORAGE_NONINTERACTIVE=1", browser)
        self.assertIn("SBERKASSA_NONINTERACTIVE=1", browser)
        self.assertIn("SBERKASSA_EXCHANGE_NONINTERACTIVE=1", browser)
        self.assertIn("collector will not enter E-ID", exchange)
        money_storage = (root / "scripts" / "money_storage_chromium_bridge.py").read_text(encoding="utf-8")
        self.assertIn("deals_form_diagnostics(cdp)", money_storage)
        diagnostics_source = (root / "scripts" / "build_three_tab_diagnostics.py").read_text(encoding="utf-8")
        self.assertIn("PAGE_DIAG deals_form=", diagnostics_source)
        self.assertIn('os.environ.get("SBERKASSA_NONINTERACTIVE") == "1"', (root / "scripts" / "sberkassa_chromium_probe.py").read_text(encoding="utf-8"))
        self.assertIn('case "$SS_STATUS" in SBERKASSA_CAPTURE_FAILED|SBERKASSA_CAPTURE_TIMEOUT|AUTH_REQUIRED|AUTH_TIMEOUT)', browser)
        self.assertIn("REFERENCE_PROFILE_REQUIRED=YES", reusable)
        self.assertIn("inputs.target != 'all'", reusable)

    def test_money_storage_pair_is_selected_through_tom_select_and_verified(self):
        root = Path(__file__).resolve().parents[1]
        bridge = (root / "scripts" / "money_storage_chromium_bridge.py").read_text(encoding="utf-8")
        self.assertIn('document.querySelector("#select_from")', bridge)
        self.assertIn('document.querySelector("#select_to")', bridge)
        self.assertIn("fromWidget.setValue(targetValue)", bridge)
        self.assertIn('selectedFrom === "USDT" && selectedTo === "ECR"', bridge)
        self.assertIn("ensure_approved_offers_pair(cdp)", bridge)
        self.assertIn("MONEY_STORAGE_PAIR_SELECTION=%s", bridge)
        self.assertNotIn('fetch("https://storage.money/public_deals/fetch', bridge)

    def test_success_report_contains_only_allowlisted_redacted_log_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            status = root / "status"
            log = root / "browser.log"
            artifact = root / "snapshot.json"
            status.write_text("OFFERS_READ_OK", encoding="utf-8")
            log.write_text(
                "OFFERS_READ_OK count=20 rate=123.45\n"
                "Authorization: Bearer should-never-appear\n"
                "REMOTE_BROWSER_URL=https://example.invalid/private-token\n"
                "OFFERS_READ_FAILED=bad\n",
                encoding="utf-8",
            )
            artifact.write_text(json.dumps({
                "pair": "USDT/ECR",
                "tab": "everyone_offers",
                "offer_count": 20,
                "rate": "123.45",
                "observed_at": "2026-11-28T10:00:00+00:00",
                "newest_offer_created_at": "2026-11-28T09:59:30+00:00",
                "freshness_window_seconds": 900,
                "freshness_confirmed": True,
            }), encoding="utf-8")
            original = diagnostics.SOURCES
            try:
                diagnostics.SOURCES = {
                    "money_storage": {
                        "status_file": status,
                        "log_file": log,
                        "expected_status": "OFFERS_READ_OK",
                        "artifact": artifact,
                        "log_pattern": diagnostics.re.compile(r"^OFFERS_READ_"),
                    }
                }
                report = diagnostics.build(root / "out")
                self.assertEqual(report["overall_status"], "ALL_THREE_COLLECTORS_SUCCESS")
                self.assertEqual(report["sources"]["money_storage"]["quote"]["offer_count"], 20)
                saved_log = (root / "out" / "logs" / "money_storage.log").read_text(encoding="utf-8")
                self.assertIn("OFFERS_READ_OK count=20", saved_log)
                self.assertNotIn("should-never-appear", saved_log)
                self.assertNotIn("private-token", saved_log)
            finally:
                diagnostics.SOURCES = original


if __name__ == "__main__":
    unittest.main()
