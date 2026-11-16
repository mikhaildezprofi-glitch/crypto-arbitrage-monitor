"""Typed data models for quotes and route calculations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum


class QuoteStatus(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


def _as_utc(value: datetime) -> datetime:
    """Normalize timestamps; naive timestamps are interpreted as UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class Quote:
    """A price expressed as quote_currency units per one base_currency."""

    source: str
    pair: str
    base_currency: str
    quote_currency: str
    rate: Decimal
    observed_at: datetime
    indicative_only: bool = False
    source_pair_id: str | None = None

    def age_seconds(self, now: datetime | None = None) -> float:
        current = _as_utc(now or datetime.now(timezone.utc))
        observed = _as_utc(self.observed_at)
        # A future observation timestamp is invalid, not a zero-age quote.
        if observed > current:
            return float("inf")
        return (current - observed).total_seconds()

    def status(self, max_age_seconds: int, now: datetime | None = None) -> QuoteStatus:
        return QuoteStatus.FRESH if self.age_seconds(now) <= max_age_seconds else QuoteStatus.STALE


@dataclass(frozen=True)
class RouteStep:
    name: str
    input_currency: str
    output_currency: str
    quote: Quote
    fee_percent: Decimal | None
    indicative_only: bool = False


@dataclass(frozen=True)
class StepResult:
    name: str
    input_amount: Decimal
    input_currency: str
    gross_output: Decimal
    fee_amount: Decimal
    net_output: Decimal
    output_currency: str
    indicative_only: bool


@dataclass(frozen=True)
class RouteResult:
    starting_amount: Decimal
    starting_currency: str
    final_amount: Decimal
    final_currency: str
    profit: Decimal
    roi_percent: Decimal
    steps: tuple[StepResult, ...]
    indicative_only: bool
