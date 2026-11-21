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
- Freshness is based on the provider-supplied `create_time` on each returned offer. Find the newest valid offer timestamp; if it is not in the future and is no more than 900 seconds older than the UTC collection time, the Money Storage offers are fresh. Exactly 900 seconds is accepted. Missing, invalid, future-dated, or older newest timestamps make the quote unavailable.
- The quote's `observed_at` is the UTC collection time from the cloud runner. Offer `create_time` values are Unix timestamps converted to UTC. The browser and Python bridge clocks are compared before collection; the runner's synchronized UTC clock is authoritative. Browser time is only a clock-consistency check, never the quote timestamp.
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

This repository includes the calculation core, read-only BlackBit and Winance API adapters, snapshot-backed Money Storage and Sberkassa quote providers, a common provider protocol, and a selectable four-source collector. The Money Storage parser normalizes raw API src=ECR/dst=USDT records to displayed USDT -> ECR direction; its snapshot provider accepts only the Everyone Offers tab and confirms freshness from the newest offer's `create_time` within 900 seconds of the UTC collection time. The Sberkassa browser probe now captures only `back_rate` and `create_time` from the successful `/public_deals/fetch` response when its exact request query is `from=ERUB&to=RUB`; its snapshot provider verifies that request metadata, snapshot age, the independent 15-minute offer freshness rule, and the first-20 `back_rate` average. The combined manual four-source workflow runs both authenticated browser bridges using their separate encrypted Chromium profiles, then fetches BlackBit and Winance and writes a four-source report. It intentionally does not calculate profit or ROI because the route ends in RUB. Human E-ID/CAPTCHA completion remains manual. The regular five-source collector remains the default. The parser and average builders do not perform network requests or authentication; official permission and a supported cloud-side access method are still required before live polling can be enabled. The collector requests all five configured source keys independently, validates each source's required currency direction and positive rate, records per-source failures, and marks the batch incomplete when any required provider is missing or fails. It never substitutes a previous quote. Telegram delivery, persistent history, and deployment are not yet implemented.

## Four-source live quote test

Run the **Four-step read-only quote test** workflow manually from GitHub Actions.
It calls the existing authenticated browser workflow twice in the same workflow
run: once with the encrypted Money Storage profile and once with the separate
encrypted Sberkassa profile. Each browser session remains human-operated; E-ID,
CAPTCHA, or other identity checks are completed manually when requested.

The browser bridges publish short-lived, normalized artifacts only:
- Money Storage: the approved Everyone Offers tab, average of the first 20
  USDT -> ECR rates, freshness from the newest offer's `create_time` (15-minute
  window) compared against the cloud runner's UTC collection time.
- Sberkassa: the exact `/public_deals/fetch?from=ERUB&to=RUB` JSON response,
  retaining only `back_rate` and `create_time` for offer rows. The request
  direction and HTTP 200 status are attached to the sanitized records. Freshness
  is confirmed when at least one offer is no older than 15 minutes; the average
  still uses the first 20 matching rows in source order.
- BlackBit and Winance: fetched through their read-only public API adapters.

The collector reports each of the four source results independently. It does
not call the fifth Sberkassa RUB -> USDT source and does not calculate final
USDT, profit, ROI, or a completed arbitrage cycle. Missing snapshots, stale
timestamps, malformed rows, or source errors are reported as unavailable.

The combined workflow uploads a one-day four-source report artifact. It does
not create a recurring schedule.

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
