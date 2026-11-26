#!/usr/bin/env python3
"""Resolve a Tailscale Funnel hostname through independent public DNS-over-HTTPS."""
import ipaddress
import json
import sys
import urllib.parse
import urllib.request

if len(sys.argv) != 2:
    raise SystemExit("usage: resolve_tailscale_funnel_ipv4.py HOSTNAME")

hostname = sys.argv[1].rstrip(".").lower()
if not hostname.endswith(".ts.net"):
    raise SystemExit("REFUSED_NON_TAILSCALE_HOSTNAME")

resolvers = (
    ("https://cloudflare-dns.com/dns-query", {"accept": "application/dns-json"}),
    ("https://dns.google/resolve", {}),
)

for endpoint, headers in resolvers:
    try:
        query = urllib.parse.urlencode({"name": hostname, "type": "A"})
        request = urllib.request.Request(
            endpoint + "?" + query,
            headers={**headers, "user-agent": "crypto-arbitrage-monitor-funnel-health/1.0"},
        )
        with urllib.request.urlopen(request, timeout=6) as response:
            payload = json.load(response)
        if payload.get("Status") != 0:
            continue
        for answer in payload.get("Answer", []):
            if answer.get("type") != 1:
                continue
            address = ipaddress.ip_address(answer.get("data", ""))
            if isinstance(address, ipaddress.IPv4Address):
                print(address)
                raise SystemExit(0)
    except SystemExit:
        raise
    except Exception:
        continue

raise SystemExit("PUBLIC_DNS_A_RECORD_NOT_READY")
