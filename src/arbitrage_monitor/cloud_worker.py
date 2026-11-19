"""One-shot cloud collection cycle and fail-closed route gate."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Mapping

from .calculator import calculate_route, five_step_route
from .models import Quote
from .providers.base import QuoteProvider
from .providers.blackbit import BlackBitQuoteProvider
from .providers.collection import REQUIRED_PROVIDER_KEYS, QuoteBatch, collect_quotes
from .providers.money_storage import MoneyStorageQuoteProvider
from .providers.winance import fetch_quote as fetch_winance_quote
from .storage import SQLiteQuoteStore


class ProviderDisabledError(RuntimeError):
    """Raised when a provider is intentionally disabled or not implemented."""


class _DisabledProvider:
    def __init__(self, reason: str) -> None:
        self.reason = reason

    def fetch_quote(self) -> Quote:
        raise ProviderDisabledError(self.reason)


class _WinanceProvider:
    def fetch_quote(self) -> Quote:
        return fetch_winance_quote()


def _enabled(name: str, default: bool = False) -> bool:
    value = os.getenv(name, str(default)).strip().lower()
    return value in {"1", "true", "yes", "on"}


def _optional_decimal(name: str) -> Decimal | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    try:
        value = Decimal(raw.strip())
    except InvalidOperation as exc:
        raise ValueError(f"{name} must be a decimal number.") from exc
    if not value.is_finite() or value < 0 or value >= 100:
        raise ValueError(f"{name} must be finite and in the range [0, 100).")
    return value


def build_provider_registry() -> dict[str, QuoteProvider]:
    """Build only explicitly enabled adapters; unsupported sources fail closed."""
    providers: dict[str, QuoteProvider] = {
        "blackbit": (
            BlackBitQuoteProvider()
            if _enabled("BLACKBIT_ENABLED", True)
            else _DisabledProvider("BlackBit is disabled by configuration.")
        ),
        "winance": (
            _WinanceProvider()
            if _enabled("WINANCE_ENABLED", True)
            else _DisabledProvider("Winance is disabled by configuration.")
        ),
    }

    if _enabled("MONEY_STORAGE_ENABLED") and _enabled("MONEY_STORAGE_CLOUD_ACCESS_APPROVED"):
        providers["money_storage"] = MoneyStorageQuoteProvider(
            from_currency=os.getenv("MONEY_STORAGE_FROM", "ECR"),
            to_currency=os.getenv("MONEY_STORAGE_TO", "USDT"),
            endpoint=os.getenv(
                "MONEY_STORAGE_API_URL",
                "https://storage.money/public_deals/fetch",
            ),
            timeout_seconds=float(os.getenv("MONEY_STORAGE_TIMEOUT_SECONDS", "20")),
        )
    else:
        providers["money_storage"] = _DisabledProvider(
            "Money Storage cloud polling is disabled; permitted cloud access is not configured."
        )

    providers["sberkassa_sell"] = _DisabledProvider(
        "Sberkassa ERUB/RUB quote adapter is not implemented; source is unverified."
    )
    providers["sberkassa_exchange"] = _DisabledProvider(
        "Sberkassa RUB/USDT quote adapter is not implemented; source is unverified."
    )
    return providers


def _quote_record(quote: Quote) -> dict[str, str | bool]:
    return {
        "pair": quote.pair,
        "rate": str(quote.rate),
        "observed_at": quote.observed_at.isoformat(),
        "indicative_only": quote.indicative_only,
    }


def _error_category(message: str) -> str:
    category, separator, _detail = message.partition(":")
    return category.strip() if separator else "ProviderUnavailable"


def run_cycle(
    providers: Mapping[str, QuoteProvider],
    store: SQLiteQuoteStore,
    *,
    fees_percent: Mapping[str, Decimal | None],
    starting_amount: Decimal = Decimal("1000"),
    max_quote_age_seconds: int = 900,
    now: datetime | None = None,
) -> dict:
    """Collect once, persist normalized state, and calculate only a complete route."""
    observed_now = now or datetime.now(timezone.utc)
    batch: QuoteBatch = collect_quotes(providers)
    store.record_batch(batch, attempted_at=observed_now)

    result = {
        "status": "incomplete",
        "complete": batch.complete,
        "observed_at": observed_now.isoformat(),
        "quotes": {
            key: _quote_record(quote)
            for key, quote in batch.quotes.items()
        },
        "errors": {
            key: _error_category(message)
            for key, message in batch.errors.items()
        },
        "route": None,
        "route_error": None,
        "source_status": store.source_status(),
    }

    if not batch.complete:
        result["route_error"] = "At least one required quote source is unavailable."
        return result

    try:
        steps = five_step_route(dict(batch.quotes), dict(fees_percent))
        route = calculate_route(
            starting_amount,
            "USDT",
            steps,
            max_quote_age_seconds=max_quote_age_seconds,
            now=observed_now,
        )
    except (KeyError, ValueError) as exc:
        result["route_error"] = str(exc)
        return result

    result["status"] = "calculated"
    result["route"] = {
        "starting_amount": str(route.starting_amount),
        "final_amount": str(route.final_amount),
        "profit": str(route.profit),
        "roi_percent": str(route.roi_percent),
        "indicative_only": route.indicative_only,
        "steps": [
            {
                "name": step.name,
                "input_amount": str(step.input_amount),
                "input_currency": step.input_currency,
                "output_amount": str(step.net_output),
                "output_currency": step.output_currency,
                "fee_amount": str(step.fee_amount),
                "indicative_only": step.indicative_only,
            }
            for step in route.steps
        ],
    }
    return result


def main() -> int:
    database_path = os.getenv("QUOTE_DATABASE_PATH", "data/quotes.sqlite3")
    fees = {
        "blackbit": _optional_decimal("FEE_BLACKBIT_PERCENT"),
        "winance": _optional_decimal("FEE_WINANCE_PERCENT"),
        "sberkassa_sell": _optional_decimal("FEE_SBERKASSA_SELL_PERCENT"),
        "sberkassa_exchange": _optional_decimal("FEE_SBERKASSA_EXCHANGE_PERCENT"),
    }
    store = SQLiteQuoteStore(database_path)
    try:
        result = run_cycle(
            build_provider_registry(),
            store,
            fees_percent=fees,
            starting_amount=Decimal(os.getenv("STARTING_AMOUNT_USDT", "1000")),
            max_quote_age_seconds=int(os.getenv("QUOTE_MAX_AGE_SECONDS", "900")),
        )
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        # An incomplete route is a valid monitoring outcome, not a worker crash.
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
