"""Collect independent provider quotes without reusing cached values."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from ..models import Quote
from .base import QuoteProvider

REQUIRED_PROVIDER_KEYS = (
    "money_storage",
    "blackbit",
    "winance",
    "sberkassa_sell",
    "sberkassa_exchange",
)


@dataclass(frozen=True)
class QuoteBatch:
    """One collection attempt; failed sources are explicit and never backfilled."""

    quotes: Mapping[str, Quote]
    errors: Mapping[str, str]

    @property
    def complete(self) -> bool:
        return not self.errors and all(key in self.quotes for key in REQUIRED_PROVIDER_KEYS)


def collect_quotes(
    providers: Mapping[str, QuoteProvider],
) -> QuoteBatch:
    """Fetch all required sources independently and retain only this cycle's results."""
    quotes: dict[str, Quote] = {}
    errors: dict[str, str] = {}

    for key in REQUIRED_PROVIDER_KEYS:
        provider = providers.get(key)
        if provider is None:
            errors[key] = "Provider is not configured."
            continue
        try:
            quote = provider.fetch_quote()
            if not isinstance(quote, Quote):
                raise TypeError("Provider did not return a Quote instance.")
            quotes[key] = quote
        except Exception as exc:
            errors[key] = f"{type(exc).__name__}: {exc}"

    return QuoteBatch(
        quotes=MappingProxyType(quotes),
        errors=MappingProxyType(errors),
    )
