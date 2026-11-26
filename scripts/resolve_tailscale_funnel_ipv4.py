#!/usr/bin/env python3
"""Resolve a Tailscale Funnel hostname through independent public DNS-over-HTTPS."""
import concurrent.futures
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
    ("cloudflare", "https://cloudflare-dns.com/dns-query", {"accept": "application/dns-json"}),
    ("google", "https://dns.google/resolve", {}),
)


def resolve(item):
    name, endpoint, headers = item
    query = urllib.parse.urlencode({"name": hostname, "type": "A"})
    request = urllib.request.Request(
        endpoint + "?" + query,
        headers={**headers, "user-agent": "crypto-arbitrage-monitor-funnel-health/1.0"},
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        payload = json.load(response)
    status = payload.get("Status")
    if status != 0:
        return name, None, f"DNS_STATUS_{status}"
    for answer in payload.get("Answer", []):
        if answer.get("type") != 1:
            continue
        try:
            address = ipaddress.ip_address(answer.get("data", ""))
        except ValueError:
            continue
        if isinstance(address, ipaddress.IPv4Address):
            return name, str(address), None
    return name, None, "DNS_NO_A_RECORD"


# Query both independent resolvers concurrently. Sequential six-second waits
# multiplied by 90 health-check attempts made transient DNS delays excessive.
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    futures = {pool.submit(resolve, item): item[0] for item in resolvers}
    for future in concurrent.futures.as_completed(futures):
        resolver_name = futures[future]
        try:
            name, address, error = future.result()
        except Exception as exc:
            print(f"DNS_RESOLVER_ERROR {resolver_name}={type(exc).__name__}", file=sys.stderr)
            continue
        if address:
            print(address)
            raise SystemExit(0)
        print(f"DNS_RESOLVER_RESULT {name}={error}", file=sys.stderr)

raise SystemExit("PUBLIC_DNS_A_RECORD_NOT_READY")
