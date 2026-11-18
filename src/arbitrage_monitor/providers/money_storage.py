"""Read-only parsing and averaging of Money Storage public USDT -> ECR offers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from ..models import Quote

MONEY_STORAGE_PAGE_SIZE = 20
MONEY_STORAGE_POLL_SECONDS = 900


@dataclass(frozen=True)
class MoneyStorageOffer:
    """One public offer, normalized to the accepting user's direction."""

    give_amount: Decimal
    give_currency: str
    receive_amount: Decimal
    receive_currency: str
    rate: Decimal
    back_rate: Decimal
    commission: Decimal | None
    commission_currency: str | None
    created_at: datetime

    @property
    def pair(self) -> str:
        return f"{self.give_currency}/{self.receive_currency}"


def _decimal(value: Any, field: str, *, optional: bool = False) -> Decimal | None:
    if value is None or value == "":
        if optional:
            return None
        raise ValueError(f"Money Storage field {field!r} is missing.")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Money Storage field {field!r} is not numeric.") from exc
    if not result.is_finite():
        raise ValueError(f"Money Storage field {field!r} must be finite.")
    return result


def parse_public_offer(row: Mapping[str, Any]) -> MoneyStorageOffer:
    """Normalize raw API fields to the displayed 'Всем предлагают' direction.

    For displayed USDT -> ECR offers, raw API fields are src=ECR and dst=USDT.
    The selected 'Всем предлагают' view is the only supported source for this project.
    Its displayed commission is intentionally excluded from route calculations.
    """
    if not isinstance(row, Mapping):
        raise TypeError("Money Storage offer must be a mapping.")

    src_currency = str(row.get("src_currency", "")).upper()
    dst_currency = str(row.get("dst_currency", "")).upper()
    if (src_currency, dst_currency) != ("ECR", "USDT"):
        raise ValueError(
            "Expected raw Money Storage pair ECR/USDT for displayed USDT/ECR; "
            f"received {src_currency}/{dst_currency}."
        )

    give_amount = _decimal(row.get("dst_amount"), "dst_amount")
    receive_amount = _decimal(row.get("src_amount"), "src_amount")
    rate = _decimal(row.get("rate"), "rate")
    back_rate = _decimal(row.get("back_rate"), "back_rate")
    commission = _decimal(row.get("commission"), "commission", optional=True)
    commission_currency = row.get("commission_currency")
    if commission_currency is not None:
        commission_currency = str(commission_currency).strip().upper() or None

    if give_amount <= 0 or receive_amount <= 0:
        raise ValueError("Money Storage offer amounts must be positive.")
    if rate <= 0 or back_rate <= 0:
        raise ValueError("Money Storage offer rates must be positive.")
    if commission is not None and commission < 0:
        raise ValueError("Money Storage commission cannot be negative.")
    if (commission is None) != (commission_currency is None):
        raise ValueError("Money Storage commission amount and currency must be supplied together.")

    try:
        timestamp = int(row["create_time"])
        created_at = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    except (KeyError, TypeError, ValueError, OverflowError, OSError) as exc:
        raise ValueError("Money Storage create_time is missing or invalid.") from exc

    return MoneyStorageOffer(
        give_amount=give_amount,
        give_currency="USDT",
        receive_amount=receive_amount,
        receive_currency="ECR",
        rate=rate,
        back_rate=back_rate,
        commission=commission,
        commission_currency=commission_currency,
        created_at=created_at,
    )


def parse_public_offers(payload: Mapping[str, Any]) -> tuple[MoneyStorageOffer, ...]:
    """Parse target-direction offers from one API page, preserving row order."""
    if not isinstance(payload, Mapping):
        raise TypeError("Money Storage response must be a mapping.")
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise ValueError("Money Storage response does not contain a data list.")

    offers: list[MoneyStorageOffer] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("Money Storage response contains a malformed offer.")
        pair = (
            str(row.get("src_currency", "")).upper(),
            str(row.get("dst_currency", "")).upper(),
        )
        if pair == ("ECR", "USDT"):
            offers.append(parse_public_offer(row))
    return tuple(offers)


def parse_public_offer_pages(
    pages: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
) -> tuple[MoneyStorageOffer, ...]:
    """Parse pages already fetched, preserving their order and repeated rows."""
    offers: list[MoneyStorageOffer] = []
    for page in pages:
        offers.extend(parse_public_offers(page))
    return tuple(offers)


def average_first_20_offer_rate(
    offers: tuple[MoneyStorageOffer, ...] | list[MoneyStorageOffer],
    *,
    observed_at: datetime | None = None,
) -> Quote:
    """Build the Money Storage quote as the arithmetic mean of the first 20 offers.

    No offer amounts are summed, no individual offer is selected, and no
    purchase or execution is implied. The quote timestamp is the observation
    time of this polling cycle, not the creation time of an individual offer.
    """
    selected = tuple(offers[:MONEY_STORAGE_PAGE_SIZE])
    if not selected:
        raise ValueError("Money Storage returned no USDT/ECR offers to average.")

    for offer in selected:
        if offer.pair != "USDT/ECR" or offer.rate <= 0:
            raise ValueError("Money Storage average contains an invalid offer.")

    average_rate = sum((offer.rate for offer in selected), Decimal("0")) / Decimal(len(selected))
    timestamp = observed_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    else:
        timestamp = timestamp.astimezone(timezone.utc)

    return Quote(
        source="money_storage",
        pair="USDT/ECR",
        base_currency="USDT",
        quote_currency="ECR",
        rate=average_rate,
        observed_at=timestamp,
    )


class MoneyStorageQuoteProvider:
    """Read the first public Money Storage page over plain HTTPS.

    This adapter intentionally has no browser-session or cookie support. It
    uses only explicitly configured public query filters and fails closed on
    authentication, rate-limit, HTTP, and response-envelope errors.
    """

    def __init__(
        self,
        *,
        from_currency: str,
        to_currency: str,
        endpoint: str = "https://storage.money/public_deals/fetch",
        timeout_seconds: float = 20.0,
    ) -> None:
        from urllib.parse import urlparse

        parsed = urlparse(endpoint)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("Money Storage endpoint must be an HTTPS URL.")
        if not from_currency.strip() or not to_currency.strip():
            raise ValueError("Money Storage from/to currency filters are required.")
        if timeout_seconds <= 0:
            raise ValueError("Money Storage timeout must be positive.")
        self.endpoint = endpoint
        self.from_currency = from_currency.strip().upper()
        self.to_currency = to_currency.strip().upper()
        self.timeout_seconds = timeout_seconds

    def fetch_quote(self) -> Quote:
        """Fetch and average the first page; never retries or reuses old data."""
        import json
        from urllib.error import HTTPError, URLError
        from urllib.parse import urlencode
        from urllib.request import Request, urlopen

        query = urlencode({
            "offset": 0,
            "limit": MONEY_STORAGE_PAGE_SIZE,
            "from": self.from_currency,
            "to": self.to_currency,
        })
        request = Request(
            f"{self.endpoint}?{query}",
            headers={"Accept": "application/json", "User-Agent": "crypto-arbitrage-monitor/0.1"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                status = getattr(response, "status", 200)
                if status != 200:
                    raise RuntimeError(f"Money Storage HTTP status {status}.")
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 401:
                raise RuntimeError("Money Storage requires authentication; no quote was published.") from exc
            if exc.code == 429:
                raise RuntimeError("Money Storage rate limit returned HTTP 429; no retry was attempted.") from exc
            raise RuntimeError(f"Money Storage HTTP error {exc.code}; no quote was published.") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"Money Storage network request failed: {type(exc).__name__}.") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Money Storage returned invalid JSON.") from exc

        if not isinstance(payload, Mapping) or payload.get("result") != "ok":
            raise ValueError("Money Storage response did not confirm result=ok.")
        offers = parse_public_offers(payload)
        return average_first_20_offer_rate(offers)
