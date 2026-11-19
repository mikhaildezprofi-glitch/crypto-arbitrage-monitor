"""Cloudflare Worker adapter. Uses Fetch and D1 bindings, never local SQLite/files."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import urlencode

from js import Object, fetch
from pyodide.ffi import to_js
from workers import Response, WorkerEntrypoint

from arbitrage_monitor.models import Quote
from arbitrage_monitor.providers.blackbit import (
    parse_ecr_usdt_pair_id,
    parse_order_book_rate,
)
from arbitrage_monitor.providers.winance import parse_winance_response


def _js_options(headers: dict[str, str]):
    return to_js({"headers": headers}, dict_converter=Object.fromEntries)


async def _get_json(url: str) -> object:
    response = await fetch(
        url,
        _js_options({
            "Accept": "application/json",
            "User-Agent": "CryptoArbitrageMonitor/0.1",
        }),
    )
    if response.status != 200:
        # Do not include response bodies, cookies, or provider data in errors.
        raise RuntimeError(f"HTTP_{response.status}")
    return json.loads(await response.text())


async def _fetch_blackbit(env) -> Quote:
    base = str(env.BLACKBIT_API_BASE_URL).rstrip("/")
    pairs = await _get_json(f"{base}/currency_pairs")
    pair_id = parse_ecr_usdt_pair_id(pairs)
    query = urlencode({"currency_pair": pair_id, "depth": 100})
    payload = await _get_json(f"{base}/v2/orders/book?{query}")
    return parse_order_book_rate(
        payload,
        pair_id=pair_id,
        observed_at=datetime.now(timezone.utc),
    )


async def _fetch_winance(env) -> Quote:
    payload = await _get_json(str(env.WINANCE_API_URL))
    return parse_winance_response(payload, observed_at=datetime.now(timezone.utc))


async def _is_due(db, source: str, interval_seconds: int, now: datetime) -> bool:
    row = await db.prepare(
        "SELECT last_attempt_at FROM source_status WHERE source = ?"
    ).bind(source).first()
    if row is None:
        return True
    last = datetime.fromisoformat(str(row["last_attempt_at"]))
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (now - last.astimezone(timezone.utc)).total_seconds() >= interval_seconds


async def _record_success(db, quote: Quote, attempted_at: datetime) -> None:
    await db.prepare(
        """INSERT INTO quote_observations
        (source, pair, base_currency, quote_currency, rate, observed_at,
         indicative_only, source_pair_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)"""
    ).bind(
        quote.source.lower(),
        quote.pair,
        quote.base_currency,
        quote.quote_currency,
        str(quote.rate),
        quote.observed_at.isoformat(),
        1 if quote.indicative_only else 0,
        quote.source_pair_id,
    ).run()
    await db.prepare(
        """INSERT INTO source_status
        (source, status, last_attempt_at, last_success_at, error_type)
        VALUES (?, 'fresh', ?, ?, NULL)
        ON CONFLICT(source) DO UPDATE SET
        status='fresh', last_attempt_at=excluded.last_attempt_at,
        last_success_at=excluded.last_success_at, error_type=NULL"""
    ).bind(
        quote.source.lower(),
        attempted_at.isoformat(),
        quote.observed_at.isoformat(),
    ).run()


async def _record_failure(db, source: str, error: Exception, attempted_at: datetime) -> None:
    # Persist only the exception class. Provider messages may contain sensitive details.
    await db.prepare(
        """INSERT INTO source_status
        (source, status, last_attempt_at, last_success_at, error_type)
        VALUES (?, 'unavailable', ?, NULL, ?)
        ON CONFLICT(source) DO UPDATE SET
        status='unavailable', last_attempt_at=excluded.last_attempt_at,
        error_type=excluded.error_type"""
    ).bind(
        source,
        attempted_at.isoformat(),
        type(error).__name__,
    ).run()


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        if str(request.method) != "GET" or str(request.url).split("?")[0].rstrip("/").endswith("/health") is False:
            return Response("Not found", status=404)
        rows = await self.env.DB.prepare(
            """SELECT source, status, last_attempt_at, last_success_at, error_type
            FROM source_status ORDER BY source"""
        ).all()
        return Response.json({"sources": rows.results})

    async def scheduled(self, controller, env, ctx):
        now = datetime.now(timezone.utc)
        max_age = int(getattr(env, "QUOTE_MAX_AGE_SECONDS", "900"))
        providers = {
            "blackbit": (
                int(getattr(env, "BLACKBIT_POLL_SECONDS", "300")),
                _fetch_blackbit,
            ),
            "winance": (
                int(getattr(env, "WINANCE_POLL_SECONDS", "300")),
                _fetch_winance,
            ),
        }

        for source, (interval, fetcher) in providers.items():
            try:
                if not await _is_due(env.DB, source, interval, now):
                    continue
                quote = await fetcher(env)
                if quote.rate <= 0 or quote.observed_at > now:
                    raise ValueError("Invalid or future-dated quote")
                age = (now - quote.observed_at).total_seconds()
                if age > max_age:
                    raise ValueError("Stale quote")
                await _record_success(env.DB, quote, now)
            except Exception as exc:
                await _record_failure(env.DB, source, exc, now)

        # Three required sources are deliberately absent: no full route is calculated.
        # This Worker only validates public-source collection and D1 persistence.
