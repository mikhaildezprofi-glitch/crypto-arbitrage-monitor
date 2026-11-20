"""Pure, read-only Sberkassa ERUB -> RUB offer quote rules.

Freshness and rate selection are intentionally independent:
- freshness is true when at least one correctly directed offer was created
  within the 15 minutes preceding the collection time;
- the rate is the arithmetic mean of back_rate from the first 20 correctly
  directed offers in source order, regardless of their creation times.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any


FRESHNESS_WINDOW = timedelta(minutes=15)
MAX_OFFERS = 20
FROM_KEYS = ("from", "from_currency", "give_currency", "currency_from", "source_currency", "src")
TO_KEYS = ("to", "to_currency", "receive_currency", "currency_to", "target_currency", "dst")


@dataclass(frozen=True)
class SberkassaOfferQuote:
    rate: Decimal | None
    fresh: bool
    fresh_offer_created_at: datetime | None
    matching_offer_count: int
    selected_offer_count: int
    reason: str | None = None

    @property
    def available(self) -> bool:
        return self.fresh and self.rate is not None and self.reason is None


def _currency_code(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("code", "symbol", "name", "currency"):
            result = _currency_code(value.get(key))
            if result:
                return result
        return None
    if isinstance(value, str):
        normalized = value.strip().upper()
        return normalized if normalized in {"ERUB", "RUB"} else None
    return None


def _direction_matches(offer: dict[str, Any]) -> bool:
    source = next((_currency_code(offer.get(key)) for key in FROM_KEYS if _currency_code(offer.get(key))), None)
    target = next((_currency_code(offer.get(key)) for key in TO_KEYS if _currency_code(offer.get(key))), None)
    return source == "ERUB" and target == "RUB"


def _parse_created_at(value: Any) -> datetime | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        if isinstance(value, (int, float)) or (isinstance(value, str) and value.strip().replace(".", "", 1).isdigit()):
            stamp = float(value)
            if stamp > 100_000_000_000:
                stamp /= 1000
            return datetime.fromtimestamp(stamp, tz=timezone.utc)
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError, OSError):
        return None
    return None


def _parse_rate(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        rate = Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        return None
    return rate if rate.is_finite() and rate > 0 else None


def _offer_rows(payload: Any):
    """Yield offer-like dictionaries in their original nested-list order."""
    if isinstance(payload, dict):
        if "back_rate" in payload:
            yield payload
        for value in payload.values():
            if isinstance(value, (dict, list)):
                yield from _offer_rows(value)
    elif isinstance(payload, list):
        for value in payload:
            if isinstance(value, (dict, list)):
                yield from _offer_rows(value)


def build_erub_rub_offer_quote(
    payload: Any,
    *,
    now: datetime | None = None,
) -> SberkassaOfferQuote:
    """Evaluate freshness across all matching offers and average first 20 rates."""
    collected_at = now or datetime.now(timezone.utc)
    if collected_at.tzinfo is None:
        collected_at = collected_at.replace(tzinfo=timezone.utc)
    collected_at = collected_at.astimezone(timezone.utc)
    cutoff = collected_at - FRESHNESS_WINDOW

    matching = [row for row in _offer_rows(payload) if _direction_matches(row)]
    fresh_times = [
        created
        for row in matching
        if (created := _parse_created_at(row.get("create_time"))) is not None
        and cutoff <= created <= collected_at
    ]
    freshest = max(fresh_times) if fresh_times else None

    selected = matching[:MAX_OFFERS]
    if not selected:
        return SberkassaOfferQuote(None, False, freshest, 0, 0, "no_matching_erub_rub_offers")

    rates = [_parse_rate(row.get("back_rate")) for row in selected]
    if any(rate is None for rate in rates):
        return SberkassaOfferQuote(None, freshest is not None, freshest, len(matching), len(selected), "invalid_back_rate_in_first_20")

    average = sum((rate for rate in rates if rate is not None), Decimal("0")) / Decimal(len(rates))
    if freshest is None:
        return SberkassaOfferQuote(average, False, None, len(matching), len(selected), "no_offer_created_within_15_minutes")
    return SberkassaOfferQuote(average, True, freshest, len(matching), len(selected))
