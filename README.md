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
- Fees are configured per step; unknown fees must remain explicitly unknown rather than assumed to be zero.
- Credentials and authenticated browser sessions must never be committed, sent to Telegram, or copied to cloud logs.

## Current implementation status

This repository starts with the calculation core and public Winance quote adapter. Other exchange adapters, Telegram delivery, persistent history, and deployment are not yet implemented.

## Run tests

```bash
python -m unittest discover -s tests -v
```

## Configuration

Environment variables:
- `WINANCE_POLL_SECONDS` (default: 300)
- `WINANCE_API_URL` (default: https://winance.exchange/site/currency_pairs)
- `QUOTE_MAX_AGE_SECONDS` (default: 900)

The Winance adapter is read-only and filters strictly for pair ID 18 / ERUB-USDT.