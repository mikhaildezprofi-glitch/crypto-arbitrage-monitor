"""One-shot read of Money Storage Everyone Offers inside an owner-authenticated cloud browser.

No cookies, tokens, local storage, or raw provider payloads are exported or persisted.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from arbitrage_monitor.providers.money_storage import (
    average_first_20_offer_rate,
    parse_public_offers,
)

OFFERS_URL = "https://storage.money/deals#tab-3"
API_URL = "https://storage.money/public_deals/fetch?offset=0&limit=20&from=ECR&to=USDT"
MAX_BODY_CHARS = 1_000_000
UPDATE_MARKER_RE = re.compile(r"(обновл|updated|refresh|last update|время обнов|последн.*курс)", re.I)
ISO_TIMESTAMP_RE = re.compile(
    r"\b(20\d{2}-\d{1,2}-\d{1,2}[ T]\d{1,2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?)"
)
DMY_TIMESTAMP_RE = re.compile(
    r"\b(\d{1,2})[./](\d{1,2})[./](20\d{2})[, ]+"
    r"(\d{1,2}):(\d{2})(?::(\d{2}))?\b"
)
TIME_ONLY_RE = re.compile(r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b")
RELATIVE_RE = re.compile(
    r"(\d+)\s*(секунд(?:ы|у)?|сек\.?|seconds?|s|мин(?:ут(?:ы|у)?)?\.?|minutes?|mins?|"
    r"час(?:а|ов)?|hours?|hrs?|д(?:ень|ня|ней)?|days?)\s*(назад|ago)?",
    re.I,
)


def parse_page_update_timestamp(
    lines: list[str] | tuple[str, ...],
    *,
    timezone_name: str,
    browser_local_now: Mapping[str, int],
) -> tuple[datetime, str]:
    """Parse the page's own update marker; never substitute the scrape time."""
    try:
        page_zone = ZoneInfo(timezone_name)
    except Exception as exc:
        raise ValueError("Money Storage browser timezone is unavailable or invalid.") from exc

    local_now = datetime(
        int(browser_local_now["year"]),
        int(browser_local_now["month"]),
        int(browser_local_now["day"]),
        int(browser_local_now["hour"]),
        int(browser_local_now["minute"]),
        int(browser_local_now.get("second", 0)),
        tzinfo=page_zone,
    )

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

    raise ValueError("Money Storage page did not expose a parseable update timestamp.")


class TransientMoneyStorageReadError(RuntimeError):
    """A read failure that is safe to retry a small, bounded number of times."""



def parse_authenticated_payload(payload: Mapping[str, Any], observed_at: datetime) -> dict[str, Any]:
    if not isinstance(payload, Mapping) or payload.get("result") != "ok":
        raise ValueError("Money Storage did not return result=ok.")
    offers = parse_public_offers(payload)
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

    page_meta = page.evaluate(
        """() => {
          const lines = (document.body ? document.body.innerText : "")
            .split(/\\n/)
            .map(line => line.trim())
            .filter(line => line && /(обновл|updated|refresh|last update|время обнов|последн.*курс)/i.test(line))
            .slice(0, 12);
          const now = new Date();
          return {
            updateLines: lines,
            timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
            localNow: {
              year: now.getFullYear(), month: now.getMonth() + 1, day: now.getDate(),
              hour: now.getHours(), minute: now.getMinutes(), second: now.getSeconds()
            }
          };
        }"""
    )
    page_updated_at, page_update_text = parse_page_update_timestamp(
        page_meta.get("updateLines", []),
        timezone_name=page_meta.get("timezone", ""),
        browser_local_now=page_meta.get("localNow", {}),
    )
    observed_now = datetime.now(timezone.utc)
    age_seconds = (observed_now - page_updated_at).total_seconds()
    if age_seconds < -60:
        raise RuntimeError("Money Storage page update timestamp is in the future.")
    if age_seconds > 900:
        raise RuntimeError("Money Storage page update timestamp is older than the 900-second source interval.")

    result = page.evaluate(
        """async (url) => {
          const response = await fetch(url, {
            method: "GET",
            headers: { "Accept": "application/json" },
            credentials: "same-origin",
            cache: "no-store",
            redirect: "follow"
          });
          const finalUrl = new URL(response.url);
          if (finalUrl.origin !== "https://storage.money") {
            return { status: response.status, finalUrl: response.url, contentType: "", text: "", invalidOrigin: true };
          }
          const declaredLength = Number(response.headers.get("content-length") || 0);
          if (Number.isFinite(declaredLength) && declaredLength > 1000000) {
            await response.body?.cancel();
            return { status: response.status, finalUrl: response.url, contentType: "", text: "", tooLarge: true };
          }
          if (!response.body) {
            return { status: response.status, finalUrl: response.url, contentType: "", text: "" };
          }
          const reader = response.body.getReader();
          const chunks = [];
          let total = 0;
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            total += value.byteLength;
            if (total > 1000000) {
              await reader.cancel();
              return { status: response.status, finalUrl: response.url, contentType: "", text: "", tooLarge: true };
            }
            chunks.push(value);
          }
          const bytes = new Uint8Array(total);
          let offset = 0;
          for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
          const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
          return { status: response.status, finalUrl: response.url, contentType: response.headers.get("content-type") || "", text };
        }""",
        API_URL,
    )
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
    snapshot = parse_authenticated_payload(payload, observed_at=page_updated_at)
    snapshot["page_updated_at"] = page_updated_at.isoformat()
    snapshot["page_update_text"] = page_update_text
    snapshot["page_timezone"] = page_meta.get("timezone")
    return snapshot


def write_normalized_snapshot(snapshot: dict[str, Any], path: str = "/tmp/money-storage-current-offers.json") -> None:
    Path(path).write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
