import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CodespacesPrivateBrowserTests(unittest.TestCase):
    def test_devcontainer_forwards_only_private_https_port(self):
        config = json.loads((ROOT / ".devcontainer/devcontainer.json").read_text())
        self.assertEqual(config["forwardPorts"], [8080])
        self.assertEqual(config["portsAttributes"]["8080"]["visibility"], "private")
        self.assertEqual(config["portsAttributes"]["8080"]["protocol"], "https")

    def test_browser_mode_bypasses_tailscale_and_keeps_auth_only(self):
        script = (ROOT / "scripts/keep_browser_and_tunnel_alive.sh").read_text()
        self.assertIn('CODESPACES_MODE="${CODESPACES_MODE:-0}"', script)
        self.assertIn('if [ "$CODESPACES_MODE" != "1" ]; then', script)
        self.assertIn('CODESPACES_PRIVATE_BROWSER_LOCAL_HEALTH=HTTP_200', script)
        self.assertIn('CODESPACES_COLLECTION=DISABLED', script)
        self.assertIn('TARGET_TABS_EXACTLY_VERIFIED; AUTH_ONLY; COLLECTION_DISABLED', script)

    def test_profile_archive_is_outside_git_checkout_and_encrypted(self):
        restore = (ROOT / ".devcontainer/restore-private-profile.sh").read_text()
        save = (ROOT / ".devcontainer/save-private-profile.sh").read_text()
        run = (ROOT / ".devcontainer/start-private-browser.sh").read_text()
        self.assertIn('/workspaces/.codespace-private-state', restore)
        self.assertIn('--cipher-algo AES256', save)
        self.assertIn('CHROMIUM_PROFILE_PASSPHRASE', save)
        self.assertIn('ln -s "$PROFILE_DIR" /tmp/eid-chromium-profile', run)
        self.assertIn('TARGET=auth_only', run)

    def test_docs_forbid_public_forwarding_and_explain_manual_auth(self):
        docs = (ROOT / ".devcontainer/README.md").read_text()
        self.assertIn('must remain **Private**', docs)
        self.assertIn('Complete E-ID/CAPTCHA/MFA yourself', docs)
        self.assertIn('No quote collectors run', docs)


if __name__ == "__main__":
    unittest.main()
