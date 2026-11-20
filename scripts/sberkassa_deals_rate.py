"""Rate-only arithmetic averaging of ERUB -> RUB Sberkassa offers.

The caller must supply only ERUB -> RUB offers. Sberkassa's displayed
ERUB -> RUB rate is taken from `back_rate`; `rate` is ignored.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

MAX_OFFERS = 20
RATE_FIELD = "back_rate"


class SberkassaQuoteError(ValueError):
    """The current Sberkassa offers cannot produce a safe indicative quote."""


def calculate_erub_rub_average(
    offers: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Average back_rate from the first 20 ERUB -> RUB offers in page order.

    The caller is responsible for filtering records to ERUB -> RUB before
    calling this function. The reciprocal `rate` field is never used.
    """
    if not isinstance(offers, Sequence) or isinstance(offers, (str, bytes)):
        raise SberkassaQuoteError("The offer collection is malformed.")
    if not offers:
        raise SberkassaQuoteError("No ERUB/RUB offers were found.")

    selected = offers[:MAX_OFFERS]
    rates: list[Decimal] = []
    for index, offer in enumerate(selected, start=1):
        if not isinstance(offer, Mapping):
            raise SberkassaQuoteError(f"Offer {index} is malformed.")
        raw = offer.get(RATE_FIELD)
        if isinstance(raw, bool) or raw is None:
            raise SberkassaQuoteError(f"Offer {index} has an invalid {RATE_FIELD}.")
        try:
            rate = Decimal(str(raw).strip().replace(",", "."))
        except (InvalidOperation, AttributeError):
            raise SberkassaQuoteError(f"Offer {index} has an invalid {RATE_FIELD}.") from None
        if not rate.is_finite() or rate <= 0:
            raise SberkassaQuoteError(f"Offer {index} has a non-positive or non-finite {RATE_FIELD}.")
        rates.append(rate)

    average = sum(rates, Decimal("0")) / Decimal(len(rates))
    return {
        "base_currency": "ERUB",
        "quote_currency": "RUB",
        "rate": float(average),
        "rate_field": RATE_FIELD,
        "offers_used": len(rates),
        "method": "arithmetic_mean_first_20",
        "indicative_only": True,
    }
