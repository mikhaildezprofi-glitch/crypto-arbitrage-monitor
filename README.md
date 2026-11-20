# Crypto Arbitrage Monitor

Private project for read-only monitoring and calculation of the five-step route:

1. Money Storage: USDT -> ECR
2. BlackBit: ECR -> USDT (displayed rate only; calculation is indicative)
3. Winance: USDT -> ERUB, using **ERUB/USDT only**, pair ID **18**
4. Sberkassa: ERUB -> RUB
5. Sberkassa Exchange: RUB -> USDT

Starting reference capital: 1000 USDT. Money Storage polling interval: 900 seconds (15 minutes). The BlackBit/Winance polling cadence remains within the agreed 900–3600-second range and has not yet been selected.

## Four-source diagnostic collection mode

A partial diagnostic collection can explicitly request only the first four route sources:

```python
from arbitrage_monitor.providers.collection import (
    FOUR_STEP_PROVIDER_KEYS,
    collect_quotes,
)

batch = collect_quotes(providers, required_keys=FOUR_STEP_PROVIDER_KEYS)
```

The selected sequence is Money Storage (USDT -> ECR), BlackBit (ECR -> USDT),
Winance (USDT -> ERUB), and Sberkassa (ERUB -> RUB). The fifth Sberkassa
Exchange source (RUB -> USDT) is not called, is not marked as missing, and
does not make this diagnostic batch incomplete. Any failure among the selected
four sources still makes the batch incomplete. Calling `collect_quotes(providers)`
without an explicit selection retains the original five-source requirement.

This is a four-source quote inspection only. It ends in RUB, so it is not a
closed USDT arbitrage cycle: do not calculate or display final USDT, profit,
ROI, or a successful arbitrage result for this mode. BlackBit remains
indicative-only.

## BlackBit quote method

- Resolve the exact ECR/USDT pair from the public `/site/currency_pairs` response.
- Request the UI order-book endpoint for that pair and read only `last_rate`.
- Ignore order-book levels, volumes, and liquidity for route calculation. The quote is indicative only and is not an execution guarantee.
- Reject missing, non-positive, non-finite, or malformed rates and unsuccessful API envelopes.

## Money Storage quote method

- The authenticated standalone-Chromium capture verified the frontend request for the "Всем предлагают" (Everyone Offers) tab, with a page size of 20. This is the explicitly selected project source. Do not substitute the "Мне предлагают" tab.
- Normalize each matching raw API row (src=ECR, dst=USDT) to the displayed USDT -> ECR direction.
- Use the arithmetic mean of the rate field across the first 20 available target-direction offers as the Money Storage quote.
- If fewer than 20 target-direction offers are returned, average the available offers; an empty result is unavailable.
- Do not select one offer, add offer amounts, combine liquidity, assume partial fills, or simulate a purchase.
- The quote timestamp comes from the page's own visible last-updated marker, not the scrape time or offer creation timestamps. The marker may be an absolute date/time or a relative age displayed by the page; it must parse successfully and be no older than the 900-second Money Storage interval. If it is missing, invalid, future-dated, or stale, the source is unavailable. Offer creation timestamps remain row metadata only.
- Per project rule, the displayed Money Storage commission is retained only as source metadata and is not deducted from this route calculation.

This is an indicative market-rate average, not a promise that a trade can be executed at that rate. The monitor does not buy, accept, create, or modify offers.

## Sberkassa quote method

- For ERUB -> RUB, use only `https://sberkassa.site/deals#tab-3`, the **«Всем предлагают»** tab. Do not substitute «Мне предлагают» or «Я предлагаю».
- First filter offers by explicit currency/direction identifiers for ERUB -> RUB. Do not infer direction from the numerical value of a rate or from a reciprocal `rate` field.
- **Freshness is checked independently from rate selection:** if at least one correctly directed offer has a valid `create_time` between the collection time and 15 minutes before it, the current offers data is considered fresh. A future timestamp or an invalid/missing timestamp does not confirm freshness.
- **Rate selection does not use `create_time`:** take the first 20 correctly directed offers in their original source order, regardless of their creation times. If fewer than 20 exist, use all of them.
- Calculate the simple arithmetic mean of `back_rate` from those first 20 offers only. Ignore `rate` completely. If there are no matching offers or any selected `back_rate` is missing, non-numeric, non-finite, zero, or negative, the quote is unavailable.
- Do not use commissions, offer amounts, volumes, reserves, min/max limits, or liquidity in the rate calculation. Do not select one offer or simulate partial fills.
- For RUB -> USDT, inspect `https://sberkassa.site/exchange` separately. Its rate and freshness must be established independently; never transfer the deals-page timestamp to this page. If it exposes one published conversion rate, use that single rate; if it exposes a list of independent offers, establish their direction and apply the agreed first-20 average.
- Sberkassa authentication starts directly at `https://sberkassa.site/login` in its own cloud Chromium run. The user completes the E-ID redirect initiated by Sberkassa in that same tab; the probe waits for the E-ID provider to be visited and for the browser to return to Sberkassa. Money Storage is not opened in this mode. Any additional consent or login is completed manually. No cookies or tokens are copied.
- The live request schema, numeric currency identifiers (if any), and permitted polling method remain unverified. The pure ERUB -> RUB calculation helper is not yet wired into the hourly collector.

## Safety and calculation rules

- Monitoring and calculations only. No order placement, withdrawals, deposits, or transfers.
- BlackBit output is labelled indicative and is not represented as executable or guaranteed profit.
- Do not use Winance ERUB/RUB.
- Do not silently reuse stale quotes. A missing or stale quote makes the full-route result unavailable.
- Reject quote timestamps that lie in the future; naive timestamps are interpreted as UTC for consistent age checks.
- Fees are configured per step; unknown fees must remain explicitly unknown rather than assumed to be zero.
- Credentials and authenticated browser sessions must never be committed, sent to Telegram, or copied to cloud logs.

## Current implementation status

This repository includes the calculation core, read-only BlackBit and Winance quote adapters, a common read-only provider protocol, a quote collector, and a pure Money Storage offer parser plus first-20 arithmetic-average quote builder. The Money Storage parser normalizes raw API src=ECR/dst=USDT records to displayed USDT -> ECR direction. The authenticated standalone-Chromium workflow has completed a real read from the "Всем предлагают" tab and produced a normalized current-offers artifact. The bridge uses the same manually authenticated browser session; it does not export cookies or automate authentication. The average builder uses the first 20 available target-direction offers and timestamps the quote from the page's confirmed visible update marker. The Money Storage poll interval is configured as 900 seconds. A pure Sberkassa ERUB -> RUB helper now applies the agreed independent 15-minute freshness check and first-20 `back_rate` average, with unit tests. It is not yet connected to a live Sberkassa provider or the hourly collection cycle. The parser and average builders do not perform network requests or authentication; official permission and a supported cloud-side access method are still required before live polling can be enabled. The collector requests all five configured source keys independently, validates each source's required currency direction and positive rate, records per-source failures, and marks the batch incomplete when any required provider is missing or fails. It never substitutes a previous quote. Telegram delivery, persistent history, and deployment are not yet implemented.

## Run tests

    PYTHONPATH=src python -m unittest discover -s tests -v

## Configuration

Environment variables:
- BLACKBIT_API_BASE_URL (default: https://blackbit.exchange/site)
- WINANCE_POLL_SECONDS (must be explicitly selected within 900–3600 seconds before polling starts)
- WINANCE_API_URL (default: https://winance.exchange/site/currency_pairs)
- QUOTE_MAX_AGE_SECONDS (must be explicitly selected after the polling cadence is chosen)

Money Storage polling interval: 900 seconds (15 minutes).
The BlackBit adapter reads only the displayed ECR/USDT last_rate and marks it indicative. The Winance adapter is read-only and filters strictly for pair ID 18 / ERUB-USDT.
