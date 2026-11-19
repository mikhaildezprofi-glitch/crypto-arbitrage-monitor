"""One-shot read of Money Storage Everyone Offers inside an owner-authenticated cloud browser.

No cookies, tokens, local storage, or raw provider payloads are exported or persisted.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from arbitrage_monitor.providers.money_storage import (
    average_first_20_offer_rate,
    parse_public_offers,
)

OFFERS_URL = "https://storage.money/deals#tab-3"
API_URL = "https://storage.money/public_deals/fetch?offset=0&limit=20&from=ECR&to=USDT"
MAX_BODY_CHARS = 1_000_000


def parse_authenticated_payload(payload: Mapping[str, Any], observed_at: datetime | None = None) -> dict[str, Any]:
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


async def fetch_from_authenticated_page(page) -> dict[str, Any]:
    if not page.url.startswith("https://storage.money/"):
        raise RuntimeError("Authenticated page is not on storage.money.")
    result = await page.evaluate(
        """async (url) => {
          const response = await fetch(url, {
            method: "GET",
            headers: { "Accept": "application/json" },
            credentials: "same-origin",
            cache: "no-store",
            redirect: "follow"
          });
          const text = await response.text();
          return { status: response.status, contentType: response.headers.get("content-type") || "", text };
        }""",
        API_URL,
    )
    if result["status"] in (401, 403, 429):
        raise RuntimeError(f"Money Storage refused the authenticated read with HTTP {result['status']}; no retry.")
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
    return parse_authenticated_payload(payload)


def write_normalized_snapshot(snapshot: dict[str, Any], path: str = "/tmp/money-storage-current-offers.json") -> None:
    Path(path).write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
