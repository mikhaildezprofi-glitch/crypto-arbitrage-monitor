# Cloud implementation plan

## Objective

Move all project development, testing, scheduling, storage, and notifications to cloud infrastructure. No phone, ADB, Termux, Polydev, or local browser dependency.

The system remains read-only. It must never create/accept/edit/cancel offers or initiate payments, transfers, deposits, or withdrawals.

## Architecture

1. Cloud worker: long-running process in a managed container/service. GitHub Actions remains CI/deployment automation, not the production scheduler.
2. Provider adapters: isolated read-only adapters for Money Storage, BlackBit, Winance, Sberkassa ERUB/RUB, and Sberkassa Exchange RUB/USDT.
3. Collector: polls each enabled provider independently. A source failure does not stop other polls, but makes the five-source batch incomplete.
4. Quote persistence: store normalized Decimal rate, pair, observed_at, source status, and redacted error category. Do not persist raw authenticated responses or credentials.
5. Freshness gate: maximum quote age 900 seconds. Failed polls never reuse stale quotes.
6. Calculator: calculate only when all five quotes are fresh, correctly directed, and required fee information is known. Money Storage displayed commission is ignored by explicit project rule.
7. Notifier: Telegram informational alerts only. No execution buttons or transaction callbacks.
8. Health/status: worker liveness and source health, without secret or personal-data exposure.

## Provider readiness

| Provider | Current evidence | Implementation status |
|---|---|---|
| Money Storage | Authenticated UI capture confirmed the "Всем предлагают" frontend request and response shape; unauthenticated cloud requests previously returned 401 and 429 | Parser ready; production polling disabled |
| BlackBit | Public currency-pairs and order-book endpoints; only displayed last_rate is used | Adapter implemented; indicative only |
| Winance | Public currency-pairs endpoint; ERUB/USDT pair ID 18 | Adapter implemented |
| Sberkassa ERUB -> RUB | No verified endpoint or response schema | Disabled |
| Sberkassa RUB -> USDT | No verified endpoint or response schema | Disabled |

Do not infer an endpoint, fee, rate, volume, or permission from a similar domain or a historical screenshot.

## Development sequence

### Stage 1: Cloud runtime foundation
- Implement a single poll-cycle entry point.
- Add a durable, minimal quote/status store.
- Add explicit provider enable/disable configuration.
- Ensure disabled providers report unavailable, never fake or reuse data.
- Add tests for partial batches, stale quotes, future timestamps, and storage recovery.

### Stage 2: Deployment packaging
- Add Dockerfile and health-check command.
- Keep secrets external to the repository.
- Document environment variables and startup/shutdown behavior.
- Run CI on GitHub Actions; do not use scheduled GitHub Actions as the permanent worker.

### Stage 3: Notifications
- Add Telegram delivery for complete profitable routes and source-health alerts.
- Send no stale or incomplete route result.
- Keep messages informational and omit transaction/action buttons.

### Stage 4: Remaining provider evidence
- Continue cloud-side public technical research only.
- Do not send provider-support requests.
- Do not probe or bypass 401/403/429 responses.
- Do not implement Money Storage or Sberkassa production authentication until a permitted cloud access method is established.

### Stage 5: Production readiness
- Verify persistence, restart recovery, source health, quote age, fee handling, and notification deduplication.
- Confirm transaction-capable actions are absent.
- Enable only sources whose cloud access and semantics are independently verified.
- The full route remains unavailable until all five sources are live and valid.

## Hosting decision

No hosting vendor is selected in this stage. Choose a managed container/runtime only after comparing free-tier limits, persistent process support, secret management, outbound HTTPS, and whether a payment card is required. Do not claim continuous operation until a real deployment and health check prove it.
