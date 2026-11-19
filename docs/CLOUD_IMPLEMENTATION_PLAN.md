# Cloud implementation plan

## Objective

Move all project development, testing, scheduling, storage, and notifications to cloud infrastructure. No phone, ADB, Termux, Polydev, or local browser dependency.

The system remains read-only. It must never create/accept/edit/cancel offers or initiate payments, transfers, deposits, or withdrawals.

## Architecture

1. Cloud worker: one-shot task packaged as a Docker container and invoked by a managed cloud scheduler. GitHub Actions is CI/deployment automation, not the production scheduler.
2. Provider adapters: isolated read-only adapters for Money Storage, BlackBit, Winance, Sberkassa ERUB/RUB, and Sberkassa Exchange RUB/USDT.
3. Collector: polls providers independently. A source failure does not stop other polls, but makes the five-source batch incomplete.
4. Quote persistence: SQLite stores normalized Decimal rate, pair, observed_at, source status, and redacted error category. It never stores raw authenticated payloads or credentials.
5. Freshness gate: maximum quote age 900 seconds. Failed polls never reuse stale quotes.
6. Calculator: calculates only when all five quotes are fresh, correctly directed, and required fee information is known. Money Storage displayed commission is ignored by explicit project rule.
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
- [x] One-shot poll-cycle entry point.
- [x] Durable SQLite quote history and source health.
- [x] Explicit provider enable/disable configuration; unverified sources fail closed.
- [x] Partial-batch, stale-quote, future-timestamp, and storage tests.
- [x] Verify the full CI run and review test output (unit tests and Docker image build both passed).

### Stage 2: Deployment packaging
- [x] Dockerfile for the one-shot cloud task.
- [x] Environment-variable configuration with unverified providers disabled.
- [ ] Select a managed scheduler/host after checking free-tier, persistence, secrets, outbound HTTPS, and payment-card requirements. Current comparison: CLOUD_HOSTING_RESEARCH.md.
- [ ] Mount persistent storage at /app/data and enforce one active task at a time; ephemeral storage is not durable.
- [ ] Prove a real cloud task execution before claiming deployment.

### Stage 3: Notifications
- [ ] Telegram delivery for complete profitable routes and source-health alerts.
- [ ] Send no stale or incomplete route result.
- [ ] Keep messages informational and omit transaction/action buttons.

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
