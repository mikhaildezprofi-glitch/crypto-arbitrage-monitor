"""Live, read-only validation of the public Winance ERUB/USDT pair."""

from __future__ import annotations

import json
from datetime import timezone
from decimal import Decimal

from arbitrage_monitor.providers.winance import fetch_quote


def main() -> int:
    quote = fetch_quote(timeout_seconds=20)
    if quote.pair != "ERUB/USDT" or quote.base_currency != "ERUB" or quote.quote_currency != "USDT":
        raise SystemExit("WINANCE_LIVE_CHECK=FAIL_INVALID_PAIR")
    if quote.source_pair_id != "18":
        raise SystemExit("WINANCE_LIVE_CHECK=FAIL_UNEXPECTED_PAIR_ID")
    if not quote.rate.is_finite() or quote.rate <= Decimal("0"):
        raise SystemExit("WINANCE_LIVE_CHECK=FAIL_INVALID_RATE")

    report = {
        "status": "ok",
        "provider": "Winance",
        "pair": quote.pair,
        "pair_id": quote.source_pair_id,
        "displayed_rate": str(quote.rate),
        "observed_at_utc": quote.observed_at.astimezone(timezone.utc).isoformat(),
        "freshness_basis": "live HTTPS API retrieval time; endpoint does not expose a quote timestamp",
        "orders_placed": False,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("WINANCE_LIVE_CHECK=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
