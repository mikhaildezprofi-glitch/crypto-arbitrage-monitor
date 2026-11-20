# Crypto Arbitrage Monitor

Private project for read-only monitoring and calculation of the five-step route:

1. Money Storage: USDT -> ECR
2. BlackBit: ECR -> USDT (displayed rate only; calculation is indicative)
3. Winance: USDT -> ERUB, using **ERUB/USDT only**, pair ID **18**
4. Sberkassa: ERUB -> RUB
5. Sberkassa Exchange: RUB -> USDT

Starting reference capital: 1000 USDT. Money Storage polling interval: 900 seconds (15 minutes). The BlackBit/Winance polling cadence remains within the agreed 900–3600-second range and has not yet been selected.

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
- Ignore individual offer creation times for freshness. Use the page's own visible update time only when it confirms a successful refresh of the offers; opening the page alone is not proof of freshness.
- For RUB -> USDT, inspect `https://sberkassa.site/exchange` separately and use that page's own confirmed update time. Never transfer the timestamp from the deals page to the exchange page.
- If a page does not confirm a successful refresh, mark that route step unavailable and do not reuse an older snapshot. The live request schema, rates, fees, limits, and permitted polling method remain unverified.

## Safety and calculation rules

- Monitoring and calculations only. No order placement, withdrawals, deposits, or transfers.
- BlackBit output is labelled indicative and is not represented as executable or guaranteed profit.
- Do not use Winance ERUB/RUB.
- Do not silently reuse stale quotes. A missing or stale quote makes the full-route result unavailable.
- Reject quote timestamps that lie in the future; naive timestamps are interpreted as UTC for consistent age checks.
- Fees are configured per step; unknown fees must remain explicitly unknown rather than assumed to be zero.
- Credentials and authenticated browser sessions must never be committed, sent to Telegram, or copied to cloud logs.

## Current implementation status

This repository includes the calculation core, read-only BlackBit and Winance quote adapters, a common read-only provider protocol, a quote collector, and a pure Money Storage offer parser plus first-20 arithmetic-average quote builder. The Money Storage parser normalizes raw API src=ECR/dst=USDT records to displayed USDT -> ECR direction. The authenticated standalone-Chromium workflow has completed a real read from the "Всем предлагают" tab and produced a normalized current-offers artifact. The bridge uses the same manually authenticated browser session; it does not export cookies or automate authentication. The average builder uses the first 20 available target-direction offers and timestamps the resulting quote at observation time. The Money Storage poll interval is configured as 900 seconds. The parser and average builder do not perform network requests or authentication; official permission and a supported cloud-side access method are still required before live polling can be enabled. The collector requests all five configured source keys independently, validates each source's required currency direction and positive rate, records per-source failures, and marks the batch incomplete when any required provider is missing or fails. It never substitutes a previous quote. Telegram delivery, persistent history, and deployment are not yet implemented.

## Run tests

    PYTHONPATH=src python -m unittest discover -s tests -v

## Configuration

Environment variables:
- BLACKBIT_API_BASE_URL (default: https://blackbit.exchange/site)\n- WINANCE_POLL_SECONDS (must be explicitly selected within 900–3600 seconds before polling starts)
- WINANCE_API_URL (default: https://winance.exchange/site/currency_pairs)
- QUOTE_MAX_AGE_SECONDS (must be explicitly selected after the polling cadence is chosen)

Money Storage polling interval: 900 seconds (15 minutes).
The BlackBit adapter reads only the displayed ECR/USDT last_rate and marks it indicative. The Winance adapter is read-only and filters strictly for pair ID 18 / ERUB-USDT.
