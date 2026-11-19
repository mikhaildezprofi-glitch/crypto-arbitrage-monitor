# Cloud-only read-only bot architecture

## Goal and hard boundaries

Run the arbitrage monitor in cloud infrastructure. The phone, ADB, Termux, Polydev, and local browser are out of the development and runtime path unless the owner explicitly re-enables them later.

The monitor reads rates and calculates the five-step route only:

1. Money Storage: USDT -> ECR, "Всем предлагают" only.
2. BlackBit: ECR -> USDT, displayed last_rate only; indicative, not executable.
3. Winance: USDT -> ERUB, pair ID 18 only.
4. Sberkassa: ERUB -> RUB.
5. Sberkassa Exchange: RUB -> USDT, current displayed rate only.

No deal creation/acceptance/editing/cancellation, payment, transfer, deposit, or withdrawal capability is allowed.

## Runtime architecture

Use a long-running cloud worker or managed container for scheduling. GitHub Actions is for CI, tests, and controlled deployment tasks; it is not the persistent authenticated browser or production scheduler.

Logical components:
- Quote providers: one isolated read-only adapter per source.
- Collector: polls providers independently and records per-source success/failure.
- Normalizer: validates currency direction, positive finite Decimal rates, timestamps, and required fee metadata.
- Quote store: persists normalized quotes, observation timestamps, source health, and redacted error categories. Never persist raw authenticated payloads or secrets.
- Calculator: calculates only when all five required quotes are fresh and all required fees are known. Money Storage commission is explicitly ignored.
- Notifier: sends informational results only; no transaction buttons or execution callbacks.
- Health/status: reports worker liveness and source health without exposing credentials or raw private data.

## Scheduling and freshness

- Money Storage target interval: 900 seconds, but production polling remains disabled until a permitted cloud access method is established.
- Winance target interval: 300 seconds.
- Quote maximum age: 900 seconds.
- BlackBit must be labelled indicative. Its displayed last_rate is not an execution or liquidity check.
- Sberkassa intervals must be set only after source freshness and access limits are established.
- A failed poll marks that source unavailable. Never reuse stale data as fresh.
- Respect HTTP 401, 403, 429, and Retry-After; do not retry around access controls.

## Authentication and secrets

- Prefer documented public read endpoints where available.
- For authenticated sources, use only a cloud-side method that is permitted for the service and explicitly owner-authorized.
- If an approved cloud login flow is available, the owner completes ordinary E-ID/MFA/CAPTCHA challenges. The worker must not bypass or automate around them.
- Do not transfer session state from Android or copy browser cookies, local storage, authorization headers, OAuth codes, or CSRF values.
- Store permitted credentials only in a cloud secret manager/KMS. Never commit them, place them in workflow artifacts, send them to Telegram, or print them in logs.
- Redact request metadata and errors before persistence.

## Provider status

| Source | Code/data status | Production polling |
|---|---|---|
| Money Storage | Parser and observed frontend schema exist; cloud access method not verified | Disabled |
| BlackBit | Public read-only adapter; displayed last_rate only | Available for indicative data |
| Winance | Public read-only adapter; pair ID 18 only | Available |
| Sberkassa ERUB -> RUB | No verified quote endpoint/schema | Disabled |
| Sberkassa RUB -> USDT | No verified quote endpoint/schema | Disabled |

A full route result must remain unavailable while any required source is disabled, missing, stale, malformed, or missing required fee information.

## Work policy

- Continue all development and tests in the cloud repository.
- No phone-side actions or Polydev tasks.
- No provider-support requests will be sent.
- Do not infer permission to automate authenticated endpoints from a browser Network capture alone.
- Do not enable a source merely because its parser or adapter exists.
- Do not merge changes to main without review and passing CI.
