"""One-shot read of Money Storage Everyone Offers inside an owner-authenticated cloud browser.

No cookies, tokens, local storage, or raw provider payloads are exported or persisted.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from arbitrage_monitor.providers.money_storage import (
    average_first_20_offer_rate,
    parse_public_offers,
)


UPDATE_MARKER_RE = re.compile(r"(обновл|updated|refresh|last update|время обнов|последн.*курс)", re.I)
ISO_TIMESTAMP_RE = re.compile(
    r"\\b(20\\d{2}-\\d{1,2}-\\d{1,2}[ T]\\d{1,2}:\\d{2}(?::\\d{2})?(?:Z|[+-]\\d{2}:?\\d{2})?)"
)
DMY_TIMESTAMP_RE = re.compile(
    r"\\b(\\d{1,2})[./](\\d{1,2})[./](20\\d{2})[, ]+"
    r"(\\d{1,2}):(\\d{2})(?::(\\d{2}))?\\b"
)
TIME_ONLY_RE = re.compile(r"\\b(\\d{1,2}):(\\d{2})(?::(\\d{2}))?\\b")
RELATIVE_RE = re.compile(
    r"(\\d+)\\s*(секунд(?:ы|у)?|сек\\.?|seconds?|s|мин(?:ут(?:ы|у)?)?\\.?|minutes?|mins?|"
    r"час(?:а|ов)?|hours?|hrs?|д(?:ень|ня|ней)?|days?)\\s*(назад|ago)?",
    re.I,
)


def parse_page_update_timestamp(
    lines: list[str] | tuple[str, ...],
    *,
    timezone_name: str,
    browser_local_now: Mapping[str, int],
) -> tuple[datetime, str]:
    """Parse a visible page update marker without substituting scrape time."""
    try:
        page_zone = ZoneInfo(timezone_name)
    except Exception as exc:
        raise ValueError("Browser page timezone is unavailable or invalid.") from exc

    try:
        local_now = datetime(
            int(browser_local_now["year"]),
            int(browser_local_now["month"]),
            int(browser_local_now["day"]),
            int(browser_local_now["hour"]),
            int(browser_local_now["minute"]),
            int(browser_local_now.get("second", 0)),
            tzinfo=page_zone,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Browser local clock metadata is incomplete or invalid.") from exc

    for line in lines:
        if not UPDATE_MARKER_RE.search(line):
            continue

        iso_match = ISO_TIMESTAMP_RE.search(line)
        if iso_match:
            raw = iso_match.group(1).replace("Z", "+00:00")
            try:
                parsed = datetime.fromisoformat(raw)
            except ValueError:
                parsed = None
            if parsed is not None:
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=page_zone)
                return parsed.astimezone(timezone.utc), line[:240]

        dmy_match = DMY_TIMESTAMP_RE.search(line)
        if dmy_match:
            day, month, year, hour, minute, second = dmy_match.groups()
            parsed = datetime(
                int(year), int(month), int(day), int(hour), int(minute),
                int(second or 0), tzinfo=page_zone
            )
            return parsed.astimezone(timezone.utc), line[:240]

        relative_match = RELATIVE_RE.search(line)
        if relative_match:
            amount = int(relative_match.group(1))
            unit = relative_match.group(2).lower()
            if "сек" in unit or unit in ("s", "second", "seconds"):
                delta = timedelta(seconds=amount)
            elif "мин" in unit or unit.startswith(("min", "mins")):
                delta = timedelta(minutes=amount)
            elif "час" in unit or unit.startswith(("hour", "hr")):
                delta = timedelta(hours=amount)
            else:
                delta = timedelta(days=amount)
            return (local_now - delta).astimezone(timezone.utc), line[:240]

        if re.search(r"(только что|just now|сейчас)", line, re.I):
            return local_now.astimezone(timezone.utc), line[:240]

        time_match = TIME_ONLY_RE.search(line)
        if time_match:
            hour, minute, second = time_match.groups()
            parsed = local_now.replace(
                hour=int(hour), minute=int(minute), second=int(second or 0), microsecond=0
            )
            if parsed - local_now > timedelta(hours=1):
                parsed -= timedelta(days=1)
            return parsed.astimezone(timezone.utc), line[:240]

    raise ValueError("Page did not expose a parseable update timestamp.")


OFFERS_URL = "https://storage.money/deals#tab-3"
API_URL = "https://storage.money/public_deals/fetch?offset=0&limit=20&from=ECR&to=USDT"
MAX_BODY_CHARS = 1_000_000


def latest_offer_created_at(offers) -> datetime:
    """Return the newest provider-supplied offer creation time."""
    if not offers:
        raise ValueError("Money Storage returned no offers with creation timestamps.")
    timestamps = [offer.created_at for offer in offers]
    if any(value.tzinfo is None for value in timestamps):
        raise ValueError("Money Storage offer creation timestamp has no timezone.")
    return max(value.astimezone(timezone.utc) for value in timestamps)


def confirm_offer_freshness(offers, *, collected_at: datetime, max_age_seconds: int = 900) -> datetime:
    """Fresh only when the newest offer was created within the last 15 minutes."""
    if collected_at.tzinfo is None:
        raise ValueError("Money Storage collection time must be timezone-aware.")
    newest = latest_offer_created_at(offers)
    age_seconds = (collected_at.astimezone(timezone.utc) - newest).total_seconds()
    if age_seconds < 0:
        raise ValueError("Money Storage newest offer creation time is in the future.")
    if age_seconds > max_age_seconds:
        raise ValueError("Money Storage newest offer is older than the 900-second freshness window.")
    return newest


class TransientMoneyStorageReadError(RuntimeError):
    """A read failure that is safe to retry a small, bounded number of times."""



def parse_authenticated_payload(payload: Mapping[str, Any], observed_at: datetime) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or payload.get("result") != "ok":
        raise ValueError("Money Storage did not return result=ok.")
    offers = parse_public_offers(payload)
    newest_offer_created_at = confirm_offer_freshness(offers, collected_at=observed_at)
    quote = average_first_20_offer_rate(offers, observed_at=observed_at)
    rows = []
    for offer in offers[:20]:
        rows.append({
            "give_amount_usdt": str(offer.give_amount),
            "receive_amount_ecr": str(offer.receive_amount),
            "rate_ecr_per_usdt": str(offer.rate),
            "offer_created_at": offer.created_at.isoformat(),
        })
    return {
        "source": "money_storage",
        "tab": "everyone_offers",
        "pair": "USDT/ECR",
        "rate": str(quote.rate),
        "observed_at": quote.observed_at.isoformat(),
        "offer_count": len(rows),
        "offers": rows,
        "newest_offer_created_at": newest_offer_created_at.isoformat(),
        "freshness_window_seconds": 900,
        "freshness_confirmed": True,
        "commission_applied": False,
        "historical_data_saved": False,
    }


def fetch_from_authenticated_page(page) -> dict[str, Any]:
    page_url = urlparse(page.url)
    if (
        page_url.scheme != "https"
        or page_url.netloc.lower() != "storage.money"
        or page_url.path.rstrip("/") != "/deals"
        or page_url.fragment != "tab-3"
    ):
        raise RuntimeError("Authenticated page is not Money Storage Deals -> «Всем предлагают».")

    runner_now = datetime.now(timezone.utc)
    browser_now_ms = page.evaluate("() => Date.now()")
    if not isinstance(browser_now_ms, (int, float)):
        raise RuntimeError("Money Storage browser clock could not be read.")
    browser_now = datetime.fromtimestamp(browser_now_ms / 1000, tz=timezone.utc)
    clock_skew_seconds = abs((runner_now - browser_now).total_seconds())
    if clock_skew_seconds > 5:
        raise RuntimeError(
            "Money Storage browser and cloud-runner clocks differ by more than 5 seconds."
        )

    # The Deals page itself requests this endpoint while rendering the offers tab.
    # Reuse that authenticated response instead of issuing a second request that can
    # trigger provider rate limits (HTTP 429).
    result = page.evaluate(
        """async () => {
          const approved = url => {
            try {
              const u = new URL(url, location.href);
              const q = u.searchParams;
              return u.protocol === "https:"
                && u.hostname === "storage.money"
                && u.pathname === "/public_deals/fetch"
                && q.getAll("offset").length === 1 && q.get("offset") === "0"
                && q.getAll("limit").length === 1 && q.get("limit") === "20"
                && q.getAll("from").length === 1 && q.get("from") === "ECR"
                && q.getAll("to").length === 1 && q.get("to") === "USDT";
            } catch (_) { return false; }
          };
          const deadline = Date.now() + 15000;
          while (Date.now() < deadline) {
            const captures = window.__moneyStorageOffersCaptures || [];
            const captured = captures.find(item => item && (approved(item.finalUrl) || approved(item.requestUrl)));
            if (captured) return captured;
            await new Promise(resolve => setTimeout(resolve, 100));
          }
          const captures = window.__moneyStorageOffersCaptures || [];
          return {
            notCaptured: true,
            observed: captures.slice(0, 12).map(item => {
              try {
                const u = new URL(item.finalUrl || item.requestUrl, location.href);
                return {
                  path: u.pathname,
                  offset: u.searchParams.getAll("offset").slice(0, 2),
                  limit: u.searchParams.getAll("limit").slice(0, 2),
                  from: u.searchParams.getAll("from").slice(0, 2),
                  to: u.searchParams.getAll("to").slice(0, 2),
                  status: item.status
                };
              } catch (_) { return { path: "unparseable" }; }
            })
          };
        }""",
        None,
    )
    if result.get("notCaptured"):
        observed = result.get("observed", [])
        safe_summary = "; ".join(
            "path=%s offset=%s limit=%s from=%s to=%s status=%s" % (
                item.get("path", "?"), item.get("offset", []), item.get("limit", []),
                item.get("from", []), item.get("to", []), item.get("status", "?")
            )
            for item in observed
        )
        raise RuntimeError(
            "Money Storage page did not expose the exact approved offers request. "
            + (safe_summary[:500] if safe_summary else "No endpoint responses were captured.")
        )
    request_url = urlparse(result.get("requestUrl") or result.get("finalUrl", ""))
    request_query = parse_qs(request_url.query)
    final_url = urlparse(result.get("finalUrl") or result.get("requestUrl", ""))
    if (
        request_url.scheme != "https"
        or request_url.netloc.lower() != "storage.money"
        or request_url.path != "/public_deals/fetch"
        or request_query.get("offset") != ["0"]
        or request_query.get("limit") != ["20"]
        or request_query.get("from") != ["ECR"]
        or request_query.get("to") != ["USDT"]
        or final_url.scheme != "https"
        or final_url.netloc.lower() != "storage.money"
        or final_url.path != "/public_deals/fetch"
    ):
        raise RuntimeError("Captured Money Storage response did not match the approved offers endpoint.")
    if result.get("invalidOrigin"):
        raise RuntimeError("Money Storage read redirected outside the approved origin.")
    if result.get("tooLarge"):
        raise RuntimeError("Money Storage response exceeded the 1 MB safety limit.")
    if result["status"] in (401, 403, 429):
        raise RuntimeError(f"Money Storage refused the authenticated read with HTTP {result['status']}; no retry.")
    if 500 <= result["status"] <= 599:
        raise TransientMoneyStorageReadError(
            f"Money Storage temporarily returned HTTP {result['status']}."
        )
    if result["status"] != 200:
        raise RuntimeError(f"Money Storage returned HTTP {result['status']}; no retry.")
    if len(result["text"]) > MAX_BODY_CHARS:
        raise RuntimeError("Money Storage response exceeded the 1 MB safety limit.")
    if "json" not in result["contentType"].lower():
        raise RuntimeError("Money Storage response was not JSON.")
    try:
        payload = json.loads(result["text"])
    except json.JSONDecodeError as exc:
        raise RuntimeError("Money Storage returned malformed JSON.") from exc
    if not isinstance(payload, Mapping) or payload.get("result") != "ok":
        raise RuntimeError("Money Storage authenticated endpoint did not return result=ok.")

    # A successful protected API response proves the browser session is
    # authenticated even when the quote itself is stale. Preserve the encrypted
    # session independently from quote freshness so the user need not repeat E-ID.
    workspace = Path(os.environ.get("GITHUB_WORKSPACE", "."))
    (workspace / "session-authenticated.txt").write_text("money_storage\\n", encoding="utf-8")

    snapshot = parse_authenticated_payload(payload, observed_at=runner_now)
    snapshot["browser_clock_skew_seconds"] = round(clock_skew_seconds, 3)
    return snapshot


def write_normalized_snapshot(snapshot: dict[str, Any], path: str = "/tmp/money-storage-current-offers.json") -> None:
    Path(path).write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
