# Crypto Arbitrage Monitor

Private project for read-only monitoring and calculation of the five-step route:

1. Money Storage: USDT -> ECR
2. BlackBit: ECR -> USDT (displayed rate only; calculation is indicative)
3. Winance: USDT -> ERUB, using **ERUB/USDT only**, pair ID **18**
4. Sberkassa: ERUB -> RUB
5. Sberkassa Exchange: RUB -> USDT

Starting reference capital: 1000 USDT. Winance polling interval: 300 seconds. Money Storage polling interval: 900 seconds (15 minutes).

## Money Storage quote method

- Read only the first page of "Мне предлагают", with a page size of 20.
- Normalize each row to the displayed USDT -> ECR direction.
- Use the arithmetic mean of the rate field across the first 20 available target-direction offers as the Money Storage quote.
- If fewer than 20 target-direction offers are returned, average the available offers; an empty result is unavailable.
- Do not select one offer, add offer amounts, combine liquidity, assume partial fills, or simulate a purchase.
- The quote timestamp is the time the page was observed during polling. The source offer creation timestamps remain available as row metadata.
- The displayed commission belongs to the offer creator/seller when we accept offers in the "Мне предлагают" direction; it is not charged to this route calculation.

This is an indicative market-rate average, not a promise that a trade can be executed at that rate. The monitor does not buy, accept, create, or modify offers.

## Safety and calculation rules

- Monitoring and calculations only. No order placement, withdrawals, deposits, or transfers.
- BlackBit output is labelled indicative and is not represented as executable or guaranteed profit.
- Do not use Winance ERUB/RUB.
- Do not silently reuse stale quotes. A missing or stale quote makes the full-route result unavailable.
- Reject quote timestamps that lie in the future; naive timestamps are interpreted as UTC for consistent age checks.
- Fees are configured per step; unknown fees must remain explicitly unknown rather than assumed to be zero.
- Credentials and authenticated browser sessions must never be committed, sent to Telegram, or copied to cloud logs.

## Current implementation status

This repository includes the calculation core, public Winance quote adapter, a common read-only provider protocol, a quote collector, and a pure Money Storage offer parser plus first-20 arithmetic-average quote builder. The Money Storage parser normalizes raw API src=ECR/dst=USDT records to displayed USDT -> ECR direction. The average builder uses the first 20 available target-direction offers and timestamps the resulting quote at observation time. The Money Storage poll interval is configured as 900 seconds. The parser and average builder do not perform network requests or authentication; a supported cloud-side data-access method is still required before live Money Storage polling can be enabled. The collector requests all five configured source keys independently, validates each source's required currency direction and positive rate, records per-source failures, and marks the batch incomplete when any required provider is missing or fails. It never substitutes a previous quote. Telegram delivery, persistent history, and deployment are not yet implemented.

## Run tests

    PYTHONPATH=src python -m unittest discover -s tests -v

## Configuration

Environment variables:
- WINANCE_POLL_SECONDS (default: 300)
- WINANCE_API_URL (default: https://winance.exchange/site/currency_pairs)
- QUOTE_MAX_AGE_SECONDS (default: 900)

Money Storage polling interval: 900 seconds (15 minutes).
The Winance adapter is read-only and filters strictly for pair ID 18 / ERUB-USDT.
