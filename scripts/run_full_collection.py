"""Run one read-only five-source collection and a normalized pre-fee route estimate."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from decimal import Decimal

from arbitrage_monitor.calculator import calculate_route, five_step_route
from arbitrage_monitor.providers.collection import REQUIRED_PROVIDER_KEYS, QuoteBatch, collect_quotes
from arbitrage_monitor.providers.factory import build_default_providers

NORMALIZED_BASIS_USDT = Decimal("1")


def build_report(
    batch: QuoteBatch,
    *,
    started_at: datetime,
    completed_at: datetime,
    max_quote_age_seconds: int | None,
) -> dict:
    sources: dict[str, dict] = {}
    fresh_quotes = {}
    for key in REQUIRED_PROVIDER_KEYS:
        quote = batch.quotes.get(key)
        if quote is None:
            sources[key] = {
                "status": "unavailable",
                "error": batch.errors.get(key, "No quote returned."),
            }
            continue
        age = quote.age_seconds(completed_at)
        status = (
            "fresh"
            if max_quote_age_seconds is not None and age <= max_quote_age_seconds
            else "stale" if max_quote_age_seconds is not None
            else "freshness_threshold_not_configured"
        )
        sources[key] = {
            "status": status,
            "source": quote.source,
            "pair": quote.pair,
            "rate": str(quote.rate),
            "observed_at_utc": quote.observed_at.astimezone(timezone.utc).isoformat(),
            "age_seconds": round(age, 3) if age != float("inf") else None,
            "indicative_only": quote.indicative_only,
        }
        if status == "fresh":
            fresh_quotes[key] = quote

    route_calculation = {
        "status": "unavailable",
        "reason": "All five source quotes must be present and fresh before route evaluation.",
        "net_profit_calculated": False,
    }
    if not batch.complete:
        route_calculation["reason"] = "One or more required source quotes are unavailable."
    elif max_quote_age_seconds is None:
        route_calculation["reason"] = "QUOTE_MAX_AGE_SECONDS is not configured."
    elif len(fresh_quotes) != len(REQUIRED_PROVIDER_KEYS):
        route_calculation["reason"] = "One or more source quotes are stale or have invalid future timestamps."
    else:
        try:
            result = calculate_route(
                starting_amount=NORMALIZED_BASIS_USDT,
                starting_currency="USDT",
                steps=five_step_route(dict(fresh_quotes)),
                max_quote_age_seconds=max_quote_age_seconds,
                now=completed_at,
            )
            route_calculation = {
                "status": "pre_fee_estimate",
                "reason": "Normalized to 1 USDT; all five fee values are temporary 0% placeholders, not actual provider fee claims.",
                "basis_amount_usdt": str(NORMALIZED_BASIS_USDT),
                "final_amount_usdt_per_basis_unit": str(result.final_amount),
                "pre_fee_change_usdt_per_basis_unit": str(result.profit),
                "pre_fee_roi_percent": str(result.roi_percent),
                "indicative_only": result.indicative_only,
                "fee_assumption": "temporary_zero_percent_for_all_five_steps",
                "net_profit_calculated": False,
                "steps": [
                    {
                        "name": step.name,
                        "input_amount": str(step.input_amount),
                        "input_currency": step.input_currency,
                        "gross_output": str(step.gross_output),
                        "fee_placeholder_percent": "0",
                        "output_amount": str(step.net_output),
                        "output_currency": step.output_currency,
                        "indicative_only": step.indicative_only,
                    }
                    for step in result.steps
                ],
            }
        except (ValueError, ArithmeticError) as exc:
            route_calculation["reason"] = f"Route validation failed: {type(exc).__name__}: {exc}"

    return {
        "schema_version": 2,
        "mode": "READ_ONLY",
        "started_at_utc": started_at.isoformat(),
        "completed_at_utc": completed_at.isoformat(),
        "required_sources": list(REQUIRED_PROVIDER_KEYS),
        "collection_complete": batch.complete,
        "route_eligible": route_calculation["status"] == "pre_fee_estimate",
        "quote_max_age_seconds": max_quote_age_seconds,
        "sources": sources,
        "route_calculation": route_calculation,
        "fund_moving_operations": False,
    }


def main() -> int:
    started = datetime.now(timezone.utc)
    providers = build_default_providers()
    batch = collect_quotes(providers)
    completed = datetime.now(timezone.utc)
    raw_max_age = os.getenv("QUOTE_MAX_AGE_SECONDS", "").strip()
    max_age = int(raw_max_age) if raw_max_age else None
    if max_age is not None and max_age <= 0:
        raise SystemExit("QUOTE_MAX_AGE_SECONDS must be a positive integer.")

    report = build_report(
        batch,
        started_at=started,
        completed_at=completed,
        max_quote_age_seconds=max_age,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    output_path = os.getenv("FULL_COLLECTION_REPORT_PATH", "full-collection-report.json")
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write(rendered)
    print(rendered, end="")
    return 0 if report["route_eligible"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
