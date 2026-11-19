"""SQLite persistence for normalized quote observations and provider health."""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING

from .models import Quote, QuoteStatus

if TYPE_CHECKING:
    from .providers.collection import QuoteBatch


def _utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


class SQLiteQuoteStore:
    """Persist normalized quote history and source health, never raw API payloads.

    A failed poll marks a source unavailable and prevents an older successful
    observation from being returned by latest_fresh_quotes().
    """

    def __init__(self, database_path: str = "data/quotes.sqlite3") -> None:
        self.database_path = database_path
        if database_path != ":memory:":
            Path(database_path).expanduser().resolve().parent.mkdir(
                parents=True, exist_ok=True
            )
        self._lock = RLock()
        self._connection = sqlite3.connect(
            database_path,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._initialize()

    def _initialize(self) -> None:
        with self._lock, self._connection:
            self._connection.execute("PRAGMA foreign_keys = ON")
            if self.database_path != ":memory:":
                self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS quote_observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    pair TEXT NOT NULL,
                    base_currency TEXT NOT NULL,
                    quote_currency TEXT NOT NULL,
                    rate TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    indicative_only INTEGER NOT NULL,
                    source_pair_id TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_quote_observations_source_id
                    ON quote_observations(source, id DESC);

                CREATE TABLE IF NOT EXISTS source_status (
                    source TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    last_attempt_at TEXT NOT NULL,
                    last_success_at TEXT,
                    error_type TEXT
                );
                """
            )

    def record_success(self, quote: Quote, *, attempted_at: datetime | None = None) -> None:
        attempt = _utc(attempted_at).isoformat()
        observed = _utc(quote.observed_at).isoformat()
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO quote_observations (
                    source, pair, base_currency, quote_currency, rate,
                    observed_at, indicative_only, source_pair_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    quote.source.lower(),
                    quote.pair,
                    quote.base_currency,
                    quote.quote_currency,
                    str(quote.rate),
                    observed,
                    int(quote.indicative_only),
                    quote.source_pair_id,
                ),
            )
            self._connection.execute(
                """
                INSERT INTO source_status (
                    source, status, last_attempt_at, last_success_at, error_type
                ) VALUES (?, ?, ?, ?, NULL)
                ON CONFLICT(source) DO UPDATE SET
                    status=excluded.status,
                    last_attempt_at=excluded.last_attempt_at,
                    last_success_at=excluded.last_success_at,
                    error_type=NULL
                """,
                (quote.source.lower(), QuoteStatus.FRESH.value, attempt, observed),
            )

    def record_failure(
        self,
        source: str,
        error: Exception | str,
        *,
        attempted_at: datetime | None = None,
    ) -> None:
        """Store only the exception class, never its message or possible secrets."""
        attempt = _utc(attempted_at).isoformat()
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO source_status (
                    source, status, last_attempt_at, last_success_at, error_type
                ) VALUES (?, ?, ?, NULL, ?)
                ON CONFLICT(source) DO UPDATE SET
                    status=excluded.status,
                    last_attempt_at=excluded.last_attempt_at,
                    error_type=excluded.error_type
                """,
                (
                    source,
                    QuoteStatus.UNAVAILABLE.value,
                    attempt,
                    error if isinstance(error, str) else type(error).__name__,
                ),
            )

    def record_batch(
        self,
        batch: QuoteBatch,
        *,
        attempted_at: datetime | None = None,
    ) -> None:
        attempt = _utc(attempted_at)
        for quote in batch.quotes.values():
            self.record_success(quote, attempted_at=attempt)
        for source, message in batch.errors.items():
            # The collector stores a sanitized string. Persist only its category,
            # not the message, because provider errors may contain sensitive data.
            error_type = message.split(":", 1)[0].strip() or "ProviderError"
            self.record_failure(
                source,
                error_type,
                attempted_at=attempt,
            )

    def latest_fresh_quotes(
        self,
        *,
        max_age_seconds: int,
        now: datetime | None = None,
    ) -> dict[str, Quote]:
        if max_age_seconds < 0:
            raise ValueError("max_age_seconds cannot be negative.")
        current = _utc(now)
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT q.*
                FROM quote_observations AS q
                JOIN source_status AS s ON s.source = q.source
                WHERE s.status = ?
                  AND q.id = (
                    SELECT MAX(q2.id)
                    FROM quote_observations AS q2
                    WHERE q2.source = q.source
                  )
                """,
                (QuoteStatus.FRESH.value,),
            ).fetchall()

        fresh: dict[str, Quote] = {}
        stale_sources: list[str] = []
        for row in rows:
            quote = Quote(
                source=row["source"],
                pair=row["pair"],
                base_currency=row["base_currency"],
                quote_currency=row["quote_currency"],
                rate=Decimal(row["rate"]),
                observed_at=datetime.fromisoformat(row["observed_at"]),
                indicative_only=bool(row["indicative_only"]),
                source_pair_id=row["source_pair_id"],
            )
            if quote.status(max_age_seconds, current) is QuoteStatus.FRESH:
                fresh[quote.source] = quote
            else:
                stale_sources.append(quote.source)

        if stale_sources:
            with self._lock, self._connection:
                self._connection.executemany(
                    """
                    UPDATE source_status
                    SET status = ?
                    WHERE source = ? AND status = ?
                    """,
                    [
                        (
                            QuoteStatus.STALE.value,
                            source,
                            QuoteStatus.FRESH.value,
                        )
                        for source in stale_sources
                    ],
                )
        return fresh

    def is_due(
        self,
        source: str,
        interval_seconds: int,
        *,
        now: datetime | None = None,
    ) -> bool:
        """Return whether a provider poll is due based on its last attempt."""
        if interval_seconds < 0:
            raise ValueError("interval_seconds cannot be negative.")
        current = _utc(now)
        with self._lock:
            row = self._connection.execute(
                "SELECT last_attempt_at FROM source_status WHERE source = ?",
                (source.lower(),),
            ).fetchone()
        if row is None:
            return True
        last_attempt = datetime.fromisoformat(row["last_attempt_at"])
        elapsed = (current - _utc(last_attempt)).total_seconds()
        return elapsed >= interval_seconds

    def source_status(self) -> dict[str, dict[str, str | None]]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT source, status, last_attempt_at, last_success_at, error_type
                FROM source_status
                ORDER BY source
                """
            ).fetchall()
        return {
            row["source"]: {
                "status": row["status"],
                "last_attempt_at": row["last_attempt_at"],
                "last_success_at": row["last_success_at"],
                "error_type": row["error_type"],
            }
            for row in rows
        }

    def close(self) -> None:
        with self._lock:
            self._connection.close()

