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
def parse_poll_seconds(raw_value: str | None) -> int | None:
    """Return an explicitly selected 15–60 minute cadence, or None if undecided."""
    if raw_value is None or not raw_value.strip():
        return None
    try:
        seconds = int(raw_value)
    except ValueError as exc:
        raise ValueError("WINANCE_POLL_SECONDS must be an integer from 900 to 3600.") from exc
    if not 900 <= seconds <= 3600:
        raise ValueError("WINANCE_POLL_SECONDS must be between 900 and 3600 seconds.")
    return seconds


POLL_SECONDS = parse_poll_seconds(os.getenv("WINANCE_POLL_SECONDS"))


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


def _normalize_pair(value: object) -> str:
    return str(value or "").upper().replace("-", "/").replace("_", "/").replace(" ", "")


def _is_target_pair(item: dict) -> bool:
    pair_id = item.get("id", item.get("currency_pair_id", item.get("pair_id")))
    pair_value = (
        item.get("symbol")
        or item.get("pair")
        or item.get("name")
        or item.get("currency_pair")
    )
    pair = _normalize_pair(pair_value)
    base = _normalize_pair(item.get("base_currency"))
    quote = _normalize_pair(item.get("quoted_currency") or item.get("quote_currency"))

    # Pair ID 18 is mandatory, but it is not sufficient by itself.
    # Every identity field supplied by the API must agree with ERUB/USDT.
    if str(pair_id) != PAIR_ID:
        return False
    if pair and pair not in {"ERUB/USDT", "ERUBUSDT"}:
        return False
    if base and base != "ERUB":
        return False
    if quote and quote != "USDT":
        return False

    # Require at least one independent symbol/currency identity signal.
    return bool(pair or (base == "ERUB" and quote == "USDT"))


def _extract_rate(item: dict) -> Decimal | None:
    for key in ("rate", "price", "last_price", "value"):
        raw = item.get(key)
        if raw is not None:
            try:
                rate = Decimal(str(raw))
                if rate.is_finite() and rate > 0:
                    return rate
            except (InvalidOperation, ValueError):
                continue
    return None


def parse_winance_response(payload: object, observed_at: datetime | None = None) -> Quote:
    if not isinstance(payload, dict):
        raise WinanceQuoteError("Winance response must be a JSON object.")
    if payload.get("result") != "ok" or payload.get("status") != 200:
        raise WinanceQuoteError("Winance API response envelope is not successful.")
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
        headers={
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "User-Agent": "CryptoArbitrageMonitor/0.1",
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            if response.status != 200:
                raise WinanceQuoteError(f"Winance API returned HTTP {response.status}.")
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise WinanceQuoteError(f"Unable to retrieve Winance quote: {exc}") from exc
    return parse_winance_response(payload)


class WinanceQuoteProvider:
    """QuoteProvider-compatible wrapper for the common route collector."""

    def __init__(self, timeout_seconds: int = 15):
        if timeout_seconds < 1:
            raise ValueError("timeout_seconds must be at least 1.")
        self.timeout_seconds = timeout_seconds

    def fetch_quote(self) -> Quote:
        return fetch_quote(timeout_seconds=self.timeout_seconds)


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
