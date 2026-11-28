"""Live, read-only validation of the public BlackBit ECR/USDT displayed rate."""

from __future__ import annotations

import json
from datetime import timezone
from decimal import Decimal

from arbitrage_monitor.providers.blackbit import fetch_quote


def main() -> int:
    quote = fetch_quote(timeout_seconds=20)
    if quote.pair != "ECR/USDT" or quote.base_currency != "ECR" or quote.quote_currency != "USDT":
        raise SystemExit("BLACKBIT_LIVE_CHECK=FAIL_INVALID_PAIR")
    if quote.source_pair_id != "6":
        raise SystemExit("BLACKBIT_LIVE_CHECK=FAIL_UNEXPECTED_PAIR_ID")
    if not quote.rate.is_finite() or quote.rate <= Decimal("0"):
        raise SystemExit("BLACKBIT_LIVE_CHECK=FAIL_INVALID_LAST_RATE")
    if not quote.indicative_only:
        raise SystemExit("BLACKBIT_LIVE_CHECK=FAIL_NOT_MARKED_INDICATIVE")

    observed = quote.observed_at.astimezone(timezone.utc)
    report = {
        "status": "ok",
        "provider": "BlackBit",
        "pair": quote.pair,
        "pair_id": quote.source_pair_id,
        "displayed_last_rate": str(quote.rate),
        "observed_at_utc": observed.isoformat(),
        "freshness_basis": "live HTTPS API retrieval time; endpoint does not expose a quote timestamp",
        "indicative_only": True,
        "order_book_levels_used": False,
        "liquidity_checked": False,
        "orders_placed": False,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("BLACKBIT_LIVE_CHECK=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
