"""Deterministic route calculations using Decimal arithmetic."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from .models import Quote, QuoteStatus, RouteResult, RouteStep, StepResult


def apply_step(amount: Decimal, step: RouteStep) -> StepResult:
    if step.fee_percent is None:
        raise ValueError(f"Fee for {step.name} is unknown; refusing to assume zero.")
    if not (Decimal("0") <= step.fee_percent < Decimal("100")):
        raise ValueError(f"Invalid fee percentage for {step.name}.")

    quote = step.quote
    if amount < 0 or quote.rate <= 0:
        raise ValueError("Amount must be non-negative and quote rate must be positive.")

    if (step.input_currency, step.output_currency) == (
        quote.base_currency, quote.quote_currency,
    ):
        gross = amount * quote.rate
    elif (step.input_currency, step.output_currency) == (
        quote.quote_currency, quote.base_currency,
    ):
        gross = amount / quote.rate
    else:
        raise ValueError(
            f"Quote {quote.pair} cannot convert {step.input_currency} to {step.output_currency}."
        )

    fee = gross * step.fee_percent / Decimal("100")
    net = gross - fee
    return StepResult(
        name=step.name,
        input_amount=amount,
        input_currency=step.input_currency,
        gross_output=gross,
        fee_amount=fee,
        net_output=net,
        output_currency=step.output_currency,
        indicative_only=step.indicative_only or quote.indicative_only,
    )


def calculate_route(
    starting_amount: Decimal,
    starting_currency: str,
    steps: tuple[RouteStep, ...],
    max_quote_age_seconds: int = 900,
    now: datetime | None = None,
) -> RouteResult:
    """Calculate only when every quote is fresh and every fee is known."""
    if starting_amount <= 0:
        raise ValueError("Starting amount must be positive.")
    if not steps:
        raise ValueError("At least one route step is required.")
    if max_quote_age_seconds < 0:
        raise ValueError("Maximum quote age cannot be negative.")

    amount = starting_amount
    currency = starting_currency
    results: list[StepResult] = []

    for step in steps:
        if step.input_currency != currency:
            raise ValueError(
                f"Route currency mismatch before {step.name}: expected {currency}, "
                f"step accepts {step.input_currency}."
            )
        if step.quote.status(max_quote_age_seconds, now) is not QuoteStatus.FRESH:
            raise ValueError(f"Quote for {step.name} is stale; full-route result is unavailable.")
        result = apply_step(amount, step)
        results.append(result)
        amount = result.net_output
        currency = result.output_currency

    if currency != starting_currency:
        raise ValueError(
            f"Route ends in {currency}, but starting currency is {starting_currency}."
        )

    profit = amount - starting_amount
    roi = profit / starting_amount * Decimal("100")
    return RouteResult(
        starting_amount=starting_amount,
        starting_currency=starting_currency,
        final_amount=amount,
        final_currency=currency,
        profit=profit,
        roi_percent=roi,
        steps=tuple(results),
        indicative_only=any(item.indicative_only for item in results),
    )


def five_step_route(
    quotes: dict[str, Quote],
    fees_percent: dict[str, Decimal | None],
) -> tuple[RouteStep, ...]:
    """Build the configured route from its five required quote keys."""
    definitions = (
        ("Money Storage", "USDT", "ECR", "money_storage", False),
        ("BlackBit", "ECR", "USDT", "blackbit", True),
        ("Winance", "USDT", "ERUB", "winance", False),
        ("Sberkassa", "ERUB", "RUB", "sberkassa_sell", False),
        ("Sberkassa Exchange", "RUB", "USDT", "sberkassa_exchange", False),
    )
    steps: list[RouteStep] = []
    for name, input_currency, output_currency, key, indicative in definitions:
        if key not in quotes:
            raise ValueError(f"Missing quote: {key}")
        # Money Storage uses only the "Всем предлагают" tab.
        # Per project instruction, its displayed commission is not included in this route.
        fee_percent = Decimal("0") if key == "money_storage" else fees_percent.get(key)
        steps.append(
            RouteStep(
                name=name,
                input_currency=input_currency,
                output_currency=output_currency,
                quote=quotes[key],
                fee_percent=fee_percent,
                indicative_only=indicative,
            )
        )
    return tuple(steps)
