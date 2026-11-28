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

# Diagnostic route requested for a four-source test. It intentionally stops
# at RUB and must never be treated as a completed arbitrage cycle.
FOUR_STEP_PROVIDER_KEYS = REQUIRED_PROVIDER_KEYS[:4]

EXPECTED_PAIRS = {
    "money_storage": ("USDT", "ECR"),
    "blackbit": ("ECR", "USDT"),
    "winance": ("ERUB", "USDT"),
    "sberkassa_sell": ("ERUB", "RUB"),
    "sberkassa_exchange": ("RUB", "USDT"),
}


@dataclass(frozen=True)
class QuoteBatch:
    """One collection attempt; failed sources are explicit and never backfilled."""

    quotes: Mapping[str, Quote]
    errors: Mapping[str, str]
    required_keys: tuple[str, ...] = REQUIRED_PROVIDER_KEYS

    @property
    def complete(self) -> bool:
        """True only when every source selected for this collection succeeded."""
        return not self.errors and all(key in self.quotes for key in self.required_keys)


def collect_quotes(
    providers: Mapping[str, QuoteProvider],
    required_keys: tuple[str, ...] = REQUIRED_PROVIDER_KEYS,
) -> QuoteBatch:
    """Fetch only the selected sources; the default remains the full five-step route."""
    if not required_keys:
        raise ValueError("At least one provider key must be selected.")
    if len(set(required_keys)) != len(required_keys):
        raise ValueError("Provider keys must be unique.")
    unknown = set(required_keys) - set(EXPECTED_PAIRS)
    if unknown:
        raise ValueError(f"Unknown provider key(s): {', '.join(sorted(unknown))}.")

    quotes: dict[str, Quote] = {}
    errors: dict[str, str] = {}

    for key in required_keys:
        provider = providers.get(key)
        if provider is None:
            errors[key] = "Provider is not configured."
            continue
        try:
            quote = provider.fetch_quote()
            if not isinstance(quote, Quote):
                raise TypeError("Provider did not return a Quote instance.")
            if quote.rate <= 0:
                raise ValueError("Provider returned a non-positive quote rate.")
            expected_pair = EXPECTED_PAIRS[key]
            actual_pair = (quote.base_currency, quote.quote_currency)
            if actual_pair != expected_pair:
                raise ValueError(
                    f"Provider returned {quote.pair} ({actual_pair[0]}/{actual_pair[1]}); "
                    f"expected {expected_pair[0]}/{expected_pair[1]}."
                )
            quotes[key] = quote
        except Exception as exc:
            errors[key] = f"{type(exc).__name__}: {exc}"

    return QuoteBatch(
        quotes=MappingProxyType(quotes),
        errors=MappingProxyType(errors),
        required_keys=tuple(required_keys),
    )
