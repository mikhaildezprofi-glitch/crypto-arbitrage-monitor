import unittest
from pathlib import Path


class TailscaleDnsResolverTests(unittest.TestCase):
    def test_dns_checks_are_parallel_bounded_and_diagnostic(self):
        root = Path(__file__).resolve().parents[1]
        resolver = (root / "scripts" / "resolve_tailscale_funnel_ipv4.py").read_text(encoding="utf-8")
        self.assertIn("ThreadPoolExecutor(max_workers=2)", resolver)
        self.assertIn("urlopen(request, timeout=3)", resolver)
        self.assertIn("DNS_RESOLVER_ERROR", resolver)
        self.assertIn("DNS_RESOLVER_RESULT", resolver)
        self.assertIn("PUBLIC_DNS_A_RECORD_NOT_READY", resolver)

    def test_funnel_loop_does_not_silence_dns_diagnostics(self):
        root = Path(__file__).resolve().parents[1]
        script = (root / "scripts" / "keep_browser_and_tunnel_alive.sh").read_text(encoding="utf-8")
        self.assertIn('TUNNEL_IP="$(python3 scripts/resolve_tailscale_funnel_ipv4.py "$TUNNEL_HOST" || true)"', script)
        self.assertNotIn('resolve_tailscale_funnel_ipv4.py "$TUNNEL_HOST" 2>/dev/null', script)


if __name__ == "__main__":
    unittest.main()
