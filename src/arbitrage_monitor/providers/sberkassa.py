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
    """Yield each offer-like dictionary once, preserving source order."""
    seen: set[int] = set()

    def walk(node: Any):
        if isinstance(node, dict):
            identity = id(node)
            if identity in seen:
                return
            seen.add(identity)
            if "back_rate" in node:
                yield node
                return
            for value in node.values():
                if isinstance(value, (dict, list)):
                    yield from walk(value)
        elif isinstance(node, list):
            for value in node:
                if isinstance(value, (dict, list)):
                    yield from walk(value)

    yield from walk(payload)



def extract_erub_rub_offer_records(payload: Any, limit: int = 500) -> list[dict[str, str | None]]:
    """Extract only back_rate/create_time from offer rows, preserving source order."""
    if limit < 1:
        raise ValueError("limit must be positive.")
    records: list[dict[str, str | None]] = []
    seen: set[int] = set()

    def walk(node: Any, depth: int = 0) -> None:
        if depth > 12 or len(records) >= limit:
            return
        if isinstance(node, dict):
            identity = id(node)
            if identity in seen:
                return
            seen.add(identity)
            if "back_rate" in node:
                back_rate = node.get("back_rate")
                create_time = node.get("create_time")
                records.append({
                    "back_rate": str(back_rate)[:64] if back_rate is not None else None,
                    "create_time": str(create_time)[:64] if create_time is not None else None,
                })
                return
            for child in node.values():
                if isinstance(child, (dict, list)):
                    walk(child, depth + 1)
        elif isinstance(node, list):
            for child in node:
                if isinstance(child, (dict, list)):
                    walk(child, depth + 1)

    walk(payload)
    return records


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


class SberkassaSnapshotQuoteProvider:
    """Read sanitized ERUB -> RUB offers captured from the exact public-deals query."""

    def __init__(self, snapshot_path: str = "sberkassa-current-inspection.json", *, max_snapshot_age_seconds: int = 900):
        if max_snapshot_age_seconds <= 0:
            raise ValueError("max_snapshot_age_seconds must be positive.")
        self.snapshot_path = snapshot_path
        self.max_snapshot_age_seconds = max_snapshot_age_seconds

    def fetch_quote(self):
        import json
        from pathlib import Path

        from ..models import Quote

        try:
            artifact = json.loads(Path(self.snapshot_path).read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise RuntimeError("Sberkassa authenticated inspection snapshot is missing.") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("Sberkassa inspection snapshot cannot be read.") from exc

        if not isinstance(artifact, dict) or artifact.get("source") != "sberkassa.site" or artifact.get("read_only") is not True:
            raise RuntimeError("Sberkassa snapshot source or read-only marker is invalid.")
        try:
            captured_at = datetime.fromisoformat(str(artifact["captured_at_utc"]).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("Sberkassa snapshot capture time is missing or invalid.") from exc
        if captured_at.tzinfo is None:
            captured_at = captured_at.replace(tzinfo=timezone.utc)
        captured_at = captured_at.astimezone(timezone.utc)
        age = (datetime.now(timezone.utc) - captured_at).total_seconds()
        if age < -60 or age > self.max_snapshot_age_seconds:
            raise RuntimeError("Sberkassa inspection snapshot is future-dated or stale.")

        page = artifact.get("pages", {}).get("deals_everyone_offers", {})
        if page.get("url_path") != "/deals#tab-3":
            raise RuntimeError("Sberkassa snapshot is not from the Everyone Offers deals tab.")
        request = page.get("offer_request", {})
        if (
            request.get("path") != "/public_deals/fetch"
            or request.get("from") != "ERUB"
            or request.get("to") != "RUB"
            or request.get("status") != 200
        ):
            raise RuntimeError("Sberkassa offers were not fetched using the verified ERUB -> RUB request.")
        records = page.get("offer_records")
        if not isinstance(records, list) or not records:
            raise RuntimeError("Sberkassa snapshot contains no normalized ERUB -> RUB offers.")

        normalized = []
        for row in records:
            if not isinstance(row, dict):
                raise RuntimeError("Sberkassa snapshot contains a malformed offer record.")
            normalized.append({
                "from_currency": "ERUB",
                "to_currency": "RUB",
                "back_rate": row.get("back_rate"),
                "create_time": row.get("create_time"),
            })
        result = build_erub_rub_offer_quote({"offers": normalized}, now=captured_at)
        if not result.available or result.rate is None:
            raise RuntimeError(result.reason or "Sberkassa ERUB -> RUB quote is unavailable.")
        return Quote(
            source="Sberkassa",
            pair="ERUB/RUB",
            base_currency="ERUB",
            quote_currency="RUB",
            rate=result.rate,
            observed_at=captured_at,
        )
