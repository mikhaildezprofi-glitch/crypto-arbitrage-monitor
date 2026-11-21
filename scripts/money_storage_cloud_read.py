"""One-shot read of Money Storage Everyone Offers inside an owner-authenticated cloud browser.

No cookies, tokens, local storage, or raw provider payloads are exported or persisted.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse

from arbitrage_monitor.providers.money_storage import (
    average_first_20_offer_rate,
    parse_public_offers,
)

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
          const deadline = Date.now() + 10000;
          while (Date.now() < deadline) {
            const captured = window.__moneyStorageOffersCapture;
            if (captured) return captured;
            await new Promise(resolve => setTimeout(resolve, 100));
          }
          return { notCaptured: true };
        }""",
        None,
    )
    if result.get("notCaptured"):
        raise RuntimeError(
            "Money Storage Deals page did not expose its initial authenticated offers response."
        )
    final_url = urlparse(result.get("finalUrl", ""))
    final_query = parse_qs(final_url.query)
    if (
        final_url.scheme != "https"
        or final_url.netloc.lower() != "storage.money"
        or final_url.path != "/public_deals/fetch"
        or final_query.get("offset") != ["0"]
        or final_query.get("limit") != ["20"]
        or final_query.get("from") != ["ECR"]
        or final_query.get("to") != ["USDT"]
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
