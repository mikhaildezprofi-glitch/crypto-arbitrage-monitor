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

    observed_now = datetime.now(timezone.utc)

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
    snapshot = parse_authenticated_payload(payload, observed_at=observed_now)
    return snapshot


def write_normalized_snapshot(snapshot: dict[str, Any], path: str = "/tmp/money-storage-current-offers.json") -> None:
    Path(path).write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
