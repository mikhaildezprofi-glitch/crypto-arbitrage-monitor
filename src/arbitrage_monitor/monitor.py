"""Minimal polling runner for the public Winance ERUB/USDT quote."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable

from .providers.winance import POLL_SECONDS, WinanceQuoteError, fetch_quote

logger = logging.getLogger("arbitrage_monitor.winance")


def run_forever(
    on_quote: Callable[[dict], None] | None = None,
    on_error: Callable[[str], None] | None = None,
    poll_seconds: int = POLL_SECONDS,
) -> None:
    """Fetch immediately, then poll every configured interval.

    Failed requests emit an error and do not reuse a previous quote.
    """
    if poll_seconds < 1:
        raise ValueError("poll_seconds must be at least 1.")
    while True:
        try:
            quote = fetch_quote()
            record = {
                "source": quote.source,
                "pair": quote.pair,
                "pair_id": quote.source_pair_id,
                "rate": str(quote.rate),
                "observed_at": quote.observed_at.isoformat(),
                "poll_seconds": poll_seconds,
                "status": "fresh",
            }
            if on_quote:
                on_quote(record)
            else:
                print(json.dumps(record, ensure_ascii=False), flush=True)
        except (WinanceQuoteError, OSError, ValueError) as exc:
            message = str(exc)
            logger.warning("Winance quote unavailable: %s", message)
            if on_error:
                on_error(message)
        time.sleep(poll_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_forever()
