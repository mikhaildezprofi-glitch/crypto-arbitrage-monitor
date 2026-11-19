# Crypto Arbitrage Monitor

Private, cloud-oriented, read-only monitor for the five-step route:

1. Money Storage: USDT -> ECR, using only "Всем предлагают".
2. BlackBit: ECR -> USDT, displayed last_rate only; indicative, not an execution check.
3. Winance: USDT -> ERUB, ERUB/USDT only, pair ID 18.
4. Sberkassa: ERUB -> RUB.
5. Sberkassa Exchange: RUB -> USDT, current displayed conversion rate only.

Starting reference capital: 1000 USDT. Target polling intervals: Winance 300 seconds; Money Storage 900 seconds, subject to an established permitted cloud access method. Maximum quote age: 900 seconds.

## Operating boundaries

- Informational monitoring and calculations only. No deal creation, acceptance, editing, cancellation, payments, transfers, deposits, or withdrawals.
- Development and runtime are cloud-only. The phone, ADB, Termux, Polydev, and local browser are not required.
- GitHub Actions is used for CI and controlled deployment tasks, not as a persistent authenticated browser session or long-running production scheduler.
- No provider-support requests will be sent.
- Never bypass CAPTCHA, MFA, device binding, HTTP access controls, or rate limits.
- Never put credentials, browser sessions, cookies, OAuth codes, or authorization headers in the repository, workflow artifacts, Telegram messages, or logs.

## Quote rules

### Money Storage
- Only the "Всем предлагают" tab is in scope. "Мне предлагают" is not used.
- The observed frontend request was GET /public_deals/fetch?offset=0&limit=20&from=ECR&to=USDT.
- Raw src=ECR,dst=USDT records map to displayed USDT -> ECR.
- Use the arithmetic mean of the first 20 matching rate values, or fewer if fewer are returned.
- Ignore the displayed commission completely.
- The parser is implemented; unattended cloud access is not verified, so production polling remains disabled.

### BlackBit
- Resolve the ECR/USDT pair from the public currency-pairs response.
- Read only last_rate; ignore order-book levels and volumes.
- Mark the quote indicative. It is not a liquidity or execution check.

### Winance
- Use ERUB/USDT pair ID 18 only.
- Do not use ERUB/RUB or other pairs.

### Sberkassa
- ERUB -> RUB and RUB -> USDT are separate quote sources.
- Neither endpoint nor response schema is verified. Both adapters remain disabled.
- A previous screenshot value is not a current quote.

## Calculation safety

- Use Decimal arithmetic.
- Require all five quotes to be fresh and correctly directed.
- Require known fee metadata for every step except Money Storage, whose displayed commission is explicitly ignored.
- Reject missing, stale, future-dated, malformed, wrong-direction, non-positive, or non-finite quotes.
- Never substitute stale data.
- BlackBit makes the overall result indicative, not guaranteed.

## Current implementation status

The repository contains the calculation core, BlackBit and Winance read-only adapters, a common provider interface, a fail-closed quote collector, and the Money Storage parser/first-20 average builder. A cloud runtime, persistent quote history, Telegram notifications, and production deployment are not yet complete. Money Storage unattended cloud access and both Sberkassa quote sources remain blocked by missing verified access evidence. The full route must not be reported as available until all five sources and required fees are valid.

## Run tests

    PYTHONPATH=src python -m unittest discover -s tests -v

## Configuration

See .env.example. Never commit real secrets.
