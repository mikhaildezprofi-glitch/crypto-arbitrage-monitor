"""Rate-only parser for Sberkassa «Всем предлагают» ERUB -> RUB offers.

This parser ignores back_rate, offer timestamps, commissions, amounts,
limits, reserves, and liquidity. Freshness is validated separately.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

MAX_OFFERS = 20


class SberkassaQuoteError(ValueError):
    """The current Sberkassa offers cannot produce a safe indicative quote."""


def _walk_offer_records(node: Any):
    if isinstance(node, dict):
        if "rate" in node:
            yield node
        for key, value in node.items():
            if key not in {"rate", "back_rate"} and isinstance(value, (dict, list)):
                yield from _walk_offer_records(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_offer_records(value)


def calculate_erub_rub_average(payload: Any) -> dict[str, Any]:
    """Average the first 20 offer rate values in payload order."""
    records = list(_walk_offer_records(payload))
    if not records:
        raise SberkassaQuoteError("No ERUB/RUB offers with a rate field were found.")

    selected = records[:MAX_OFFERS]
    rates: list[Decimal] = []
    for index, record in enumerate(selected, start=1):
        raw = record.get("rate")
        if isinstance(raw, bool) or raw is None:
            raise SberkassaQuoteError(f"Offer {index} has an invalid rate.")
        try:
            rate = Decimal(str(raw).strip().replace(",", "."))
        except (InvalidOperation, AttributeError):
            raise SberkassaQuoteError(f"Offer {index} has an invalid rate.") from None
        if not rate.is_finite() or rate <= 0:
            raise SberkassaQuoteError(f"Offer {index} has a non-positive or non-finite rate.")
        rates.append(rate)

    average = sum(rates, Decimal("0")) / Decimal(len(rates))
    return {
        "base_currency": "ERUB",
        "quote_currency": "RUB",
        "rate": float(average),
        "offers_used": len(rates),
        "method": "arithmetic_mean_first_20",
        "indicative_only": True,
        "back_rate_used": False,
    }
