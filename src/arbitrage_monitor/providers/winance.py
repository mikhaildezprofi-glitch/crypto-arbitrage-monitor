"""Read-only Winance quote adapter for ERUB/USDT pair ID 18 only."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.error import URLError
from urllib.request import Request, urlopen

from ..models import Quote

API_URL = os.getenv(
    "WINANCE_API_URL",
    "https://winance.exchange/site/currency_pairs",
)
PAIR_ID = "18"
POLL_SECONDS = int(os.getenv("WINANCE_POLL_SECONDS", "300"))


class WinanceQuoteError(RuntimeError):
    """Raised when the Winance response cannot provide the required pair."""


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _is_target_pair(item: dict) -> bool:
    pair_id = item.get("id", item.get("currency_pair_id", item.get("pair_id")))
    pair = str(
        item.get("symbol")
        or item.get("pair")
        or item.get("name")
        or item.get("currency_pair")
        or ""
    ).upper().replace("-", "/").replace("_", "/").replace(" ", "")
    return str(pair_id) == PAIR_ID or pair in {"ERUB/USDT", "ERUBUSDT"}


def _extract_rate(item: dict) -> Decimal | None:
    for key in ("rate", "price", "last_price", "value"):
        raw = item.get(key)
        if raw is not None:
            try:
                rate = Decimal(str(raw))
                if rate > 0:
                    return rate
            except (InvalidOperation, ValueError):
                continue
    return None


def parse_winance_response(payload: object, observed_at: datetime | None = None) -> Quote:
    matches = [item for item in _walk(payload) if _is_target_pair(item)]
    for item in matches:
        rate = _extract_rate(item)
        if rate is not None:
            return Quote(
                source="Winance",
                pair="ERUB/USDT",
                base_currency="ERUB",
                quote_currency="USDT",
                rate=rate,
                observed_at=observed_at or datetime.now(timezone.utc),
                indicative_only=False,
                source_pair_id=PAIR_ID,
            )
    raise WinanceQuoteError("Winance API did not return a usable ERUB/USDT quote for pair ID 18.")


def fetch_quote(timeout_seconds: int = 15) -> Quote:
    request = Request(
        API_URL,
        headers={"Accept": "application/json", "User-Agent": "CryptoArbitrageMonitor/0.1"},
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            if response.status != 200:
                raise WinanceQuoteError(f"Winance API returned HTTP {response.status}.")
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise WinanceQuoteError(f"Unable to retrieve Winance quote: {exc}") from exc
    return parse_winance_response(payload)


if __name__ == "__main__":
    quote = fetch_quote()
    print(
        json.dumps(
            {
                "source": quote.source,
                "pair": quote.pair,
                "pair_id": quote.source_pair_id,
                "rate": str(quote.rate),
                "observed_at": quote.observed_at.isoformat(),
                "poll_seconds": POLL_SECONDS,
            },
            ensure_ascii=False,
        )
    )
