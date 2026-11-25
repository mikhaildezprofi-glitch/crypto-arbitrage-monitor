import unittest
from pathlib import Path


class MoneyStorageSessionVerificationWorkflowTests(unittest.TestCase):
    def test_restored_session_check_requires_three_fresh_offers_reads(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github" / "workflows" / "browserless-eid-handoff-stable.yml").read_text(encoding="utf-8")
        verification = workflow.split("verify-restored-money-storage-session:", 1)[1]
        verification = verification.split("      - name: Upload sanitized session-check diagnostics", 1)[0]

        self.assertIn("for attempt in 1 2 3; do", verification)
        self.assertIn("MONEY_STORAGE_NONINTERACTIVE=1", verification)
        self.assertIn('STATUS" != "OFFERS_READ_OK"', verification)
        self.assertIn("money-storage-current-offers.json", verification)
        self.assertIn('snapshot.get("tab") != "everyone_offers"', verification)
        self.assertIn('snapshot.get("pair") != "USDT/ECR"', verification)
        self.assertIn('snapshot.get("freshness_confirmed") is not True', verification)
        self.assertIn("1 <= count <= 20", verification)
        self.assertIn("age > 900", verification)
        self.assertIn("SESSION_CHECK_RESULT=3_OF_3_SUCCESS", verification)
        self.assertNotIn('STATUS" != "SESSION_AUTHENTICATED"', verification)
        self.assertNotIn("for attempt in 1;", verification)


if __name__ == "__main__":
    unittest.main()
