# Crypto Arbitrage Monitor

Private project for read-only monitoring and calculation of the five-step route:

1. Money Storage: USDT -> ECR
2. BlackBit: ECR -> USDT (displayed rate only; calculation is indicative)
3. Winance: USDT -> ERUB, using **ERUB/USDT only**, pair ID **18**
4. Sberkassa: ERUB -> RUB
5. Sberkassa Exchange: RUB -> USDT

Starting capital: 1000 USDT. Winance polling interval: 300 seconds.

## Safety and calculation rules

- Monitoring and calculations only. No order placement, withdrawals, deposits, or transfers.
- BlackBit output is labelled indicative and is not represented as executable or guaranteed profit.
- Do not use Winance ERUB/RUB.
- Do not silently reuse stale quotes. A missing or stale quote makes the full-route result unavailable.
- Reject quote timestamps that lie in the future; naive timestamps are interpreted as UTC for consistent age checks.
- Fees are configured per step; unknown fees must remain explicitly unknown rather than assumed to be zero.
- Money Storage route direction uses only offers from "Мне предлагают": when we accept another party's offer, the offer creator/seller pays the displayed commission. The seller-side commission is retained in offer data for reference but is not charged to our route. If we create an offer and another party accepts it, the commission is ours; that is a separate direction and is not part of the monitored route.
- Credentials and authenticated browser sessions must never be committed, sent to Telegram, or copied to cloud logs.

## Current implementation status

This repository includes the calculation core, public Winance quote adapter, a common read-only provider protocol, a quote collector, and a pure Money Storage public-offer parser. Money Storage public offers are returned in the reverse raw API direction: for displayed USDT -> ECR offers, API src is ECR and dst is USDT. The parser normalizes each discrete offer to the accepting user's displayed direction and preserves commission fields. For this accepting-user direction, the offer creator/seller pays the commission, so the route calculator does not charge it to our starting capital. Creating our own offer is a different fee direction and is not included in this route. The current public UI requests 20 records initially, then advances `offset` by 20 on scroll and continues while a page contains 20 records; the pure parser can normalize multiple already-fetched pages but does not perform network requests. A selector can choose the highest-rate fresh individual offer that fits the available USDT budget; ties prefer the newest offer and then the smaller amount. It only evaluates the supplied pages, preserves repeated-looking rows as separate offers, and never combines offers or assumes partial fills. It does not authenticate, call private endpoints, assume partial fills, or treat one 20-row page as the complete market. The cloud provider integration remains blocked until an official supported server-side access method and fee/offer execution semantics are established. The collector requests all five configured source keys independently, validates each source's required currency direction and positive rate, records per-source failures, and marks the batch incomplete when any required provider is missing or fails. It never substitutes a previous quote. Telegram delivery, persistent history, and deployment are not yet implemented.

## Run tests

    PYTHONPATH=src python -m unittest discover -s tests -v

## Configuration

Environment variables:
- WINANCE_POLL_SECONDS (default: 300)
- WINANCE_API_URL (default: https://winance.exchange/site/currency_pairs)
- QUOTE_MAX_AGE_SECONDS (default: 900)

The Winance adapter is read-only and filters strictly for pair ID 18 / ERUB-USDT.