"""Rate-only arithmetic averaging for an already direction-filtered Sberkassa offer list.

The caller must establish that the supplied records are ERUB -> RUB offers and
explicitly select the matching displayed-rate field. This module never guesses
between `rate` and `back_rate`.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

MAX_OFFERS = 20
ALLOWED_RATE_FIELDS = {"rate", "back_rate"}


class SberkassaQuoteError(ValueError):
    """The current Sberkassa offers cannot produce a safe indicative quote."""


def calculate_erub_rub_average(
    offers: Sequence[Mapping[str, Any]], *, rate_field: str
) -> dict[str, Any]:
    """Average the first 20 selected offer rates in their original order.

    `offers` must already contain only ERUB -> RUB records. `rate_field` is
    mandatory because Sberkassa exposes reciprocal `rate` and `back_rate`
    values and the correct displayed direction must be verified upstream.
    """
    if rate_field not in ALLOWED_RATE_FIELDS:
        raise SberkassaQuoteError("An explicit supported rate field is required.")
    if not isinstance(offers, Sequence) or isinstance(offers, (str, bytes)):
        raise SberkassaQuoteError("The offer collection is malformed.")
    if not offers:
        raise SberkassaQuoteError("No ERUB/RUB offers were found.")

    selected = offers[:MAX_OFFERS]
    rates: list[Decimal] = []
    for index, offer in enumerate(selected, start=1):
        if not isinstance(offer, Mapping):
            raise SberkassaQuoteError(f"Offer {index} is malformed.")
        raw = offer.get(rate_field)
        if isinstance(raw, bool) or raw is None:
            raise SberkassaQuoteError(f"Offer {index} has an invalid {rate_field}.")
        try:
            rate = Decimal(str(raw).strip().replace(",", "."))
        except (InvalidOperation, AttributeError):
            raise SberkassaQuoteError(f"Offer {index} has an invalid {rate_field}.") from None
        if not rate.is_finite() or rate <= 0:
            raise SberkassaQuoteError(f"Offer {index} has a non-positive or non-finite {rate_field}.")
        rates.append(rate)

    average = sum(rates, Decimal("0")) / Decimal(len(rates))
    return {
        "base_currency": "ERUB",
        "quote_currency": "RUB",
        "rate": float(average),
        "rate_field": rate_field,
        "offers_used": len(rates),
        "method": "arithmetic_mean_first_20",
        "indicative_only": True,
    }
