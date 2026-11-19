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

## Cloud runtime

A one-shot cloud worker is available:

    PYTHONPATH=src python -m arbitrage_monitor.cloud_worker

It polls each source according to its own persisted interval, reuses only still-fresh cached quotes between polls, stores normalized quote history and source health in SQLite, and emits one JSON result. An incomplete route is a normal monitoring outcome and does not make the worker crash. The Dockerfile packages the same one-shot task for a managed cloud scheduler. The scheduler must serialize runs and mount persistent storage at /app/data; an ephemeral container filesystem would lose quote history. No production hosting vendor or scheduler is configured yet. See docs/CLOUD_HOSTING_RESEARCH.md for the current comparison.

Money Storage and both Sberkassa sources are disabled by default. The worker must not be scheduled for production route alerts until all five sources and required fee data are valid.

## Current implementation status

The repository contains the calculation core, BlackBit and Winance read-only adapters, the Money Storage parser/first-20 average builder, the fail-closed collector, SQLite quote history/source health, and the one-shot cloud worker. Telegram notifications, provider adapters for Sberkassa, an approved Money Storage cloud access method, and production deployment remain incomplete.

## Run tests

    PYTHONPATH=src python -m unittest discover -s tests -v

## Configuration

See .env.example. Never commit real secrets.
