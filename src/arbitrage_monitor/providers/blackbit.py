"""Read-only BlackBit ECR/USDT quote adapter.

Only the displayed last_rate is used. Order-book levels and volumes are
intentionally ignored; this quote is indicative and not an execution check.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..models import Quote

API_BASE_URL = os.getenv("BLACKBIT_API_BASE_URL", "https://blackbit.exchange/site").rstrip("/")
ORDER_BOOK_DEPTH = 100


class BlackBitQuoteError(RuntimeError):
    """Raised when BlackBit cannot provide a valid displayed ECR/USDT rate."""


def _check_envelope(payload: object, endpoint: str) -> dict:
    if not isinstance(payload, dict):
        raise BlackBitQuoteError(f"BlackBit {endpoint} response must be a JSON object.")
    if payload.get("result") != "ok":
        raise BlackBitQuoteError(f"BlackBit {endpoint} response result is not ok.")
    if payload.get("status") != 200:
        raise BlackBitQuoteError(f"BlackBit {endpoint} response status is not 200.")
    return payload


def _normalize_pair(value: object) -> str:
    return str(value or "").upper().replace("-", "/").replace("_", "/").replace(" ", "")


def parse_ecr_usdt_pair_id(payload: object) -> str:
    """Resolve the exact ECR/USDT pair ID from the public currency-pairs response."""
    data = _check_envelope(payload, "currency-pairs")
    rows = data.get("currency_pairs")
    if not isinstance(rows, list):
        raise BlackBitQuoteError("BlackBit currency-pairs response has no currency_pairs list.")

    matches: list[str] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        name = _normalize_pair(item.get("name") or item.get("symbol") or item.get("pair"))
        base = _normalize_pair(item.get("base_currency"))
        quote = _normalize_pair(item.get("quoted_currency") or item.get("quote_currency"))
        if name and name != "ECR/USDT":
            continue
        if base and base != "ECR":
            continue
        if quote and quote != "USDT":
            continue
        if name == "ECR/USDT" or (base == "ECR" and quote == "USDT"):
            pair_id = str(item.get("id") or item.get("currency_pair_id") or "")
            if pair_id.isdigit() and int(pair_id) > 0:
                matches.append(pair_id)

    unique = tuple(dict.fromkeys(matches))
    if len(unique) != 1:
        raise BlackBitQuoteError(
            "BlackBit did not return exactly one identifiable ECR/USDT pair."
        )
    return unique[0]


def parse_order_book_rate(
    payload: object,
    *,
    pair_id: str,
    observed_at: datetime | None = None,
) -> Quote:
    """Create an indicative quote from last_rate only; ignore all order-book levels."""
    data = _check_envelope(payload, "order-book")
    raw_rate = data.get("last_rate")
    try:
        rate = Decimal(str(raw_rate))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise BlackBitQuoteError("BlackBit last_rate is missing or invalid.") from exc
    if not rate.is_finite() or rate <= 0:
        raise BlackBitQuoteError("BlackBit last_rate must be finite and positive.")

    return Quote(
        source="BlackBit",
        pair="ECR/USDT",
        base_currency="ECR",
        quote_currency="USDT",
        rate=rate,
        observed_at=observed_at or datetime.now(timezone.utc),
        indicative_only=True,
        source_pair_id=pair_id,
    )


def _get_json(path: str, *, timeout_seconds: int) -> object:
    request = Request(
        f"{API_BASE_URL}{path}",
        headers={"Accept": "application/json", "User-Agent": "CryptoArbitrageMonitor/0.1"},
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            if response.status != 200:
                raise BlackBitQuoteError(f"BlackBit API returned HTTP {response.status}.")
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise BlackBitQuoteError(f"BlackBit API returned HTTP {exc.code}.") from exc
    except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BlackBitQuoteError(f"Unable to retrieve BlackBit quote: {exc}") from exc


def fetch_quote(timeout_seconds: int = 15) -> Quote:
    """Fetch pair metadata, then the UI's order-book endpoint and read last_rate."""
    pairs = _get_json("/currency_pairs", timeout_seconds=timeout_seconds)
    pair_id = parse_ecr_usdt_pair_id(pairs)
    query = urlencode({"currency_pair": pair_id, "depth": ORDER_BOOK_DEPTH})
    book = _get_json(f"/v2/orders/book?{query}", timeout_seconds=timeout_seconds)
    return parse_order_book_rate(book, pair_id=pair_id)


class BlackBitQuoteProvider:
    """QuoteProvider-compatible wrapper for the common five-source collector."""

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
                "indicative_only": quote.indicative_only,
            },
            ensure_ascii=False,
        )
    )
