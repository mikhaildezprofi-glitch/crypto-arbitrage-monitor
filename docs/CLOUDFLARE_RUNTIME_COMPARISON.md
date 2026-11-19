# Cloudflare runtime comparison: Python/Pyodide vs JavaScript

Status: static and CI-backed prototype comparison only. No Cloudflare deployment, remote D1 database, Cron trigger, or live CPU telemetry has been used.

## Current evidence

Both implementations have passed their repository CI checks:
- Python Worker: Wrangler dry-run, shared-core vendoring, local D1 scheduled-handler smoke test.
- JavaScript Worker: parser and scheduled-handler tests, bounded-response tests, health freshness regression tests, synthetic Node benchmark, Wrangler dry-run.
- Shared project: Python unit tests and Docker build.

These checks establish packaging and local behavior, not remote Cloudflare Free-plan feasibility.

## Comparison

| Area | Python Worker | JavaScript Worker |
|---|---|---|
| Runtime | Pyodide / Python Workers | Native Workers JavaScript runtime |
| Domain parsing | Reuses the project's Python parsers and `Quote` model | Has separate JS parsers; behavior can drift from the core Python implementation |
| Network timeout | No explicit timeout in the current adapter | 8-second AbortSignal timeout |
| Response size bound | No explicit response byte cap | Streaming 1 MB cap, including declared Content-Length check |
| Payload complexity | Relies on shared parser behavior | Iterative Winance traversal with depth and node limits |
| D1 success writes | Quote and source status are written sequentially | Quote and source status are grouped with D1 `batch()` |
| Provider failure isolation | A failure while writing failure status can escape the loop | Failure-status write is isolated so the other provider can still be polled |
| Configuration validation | Poll/freshness values are converted with `int()` but not range-validated | Poll/freshness values require positive safe integers |
| Health freshness | Returns persisted status; it does not recalculate age on request | Recalculates age and marks expired or future-dated observations stale |
| Local evidence | Local Wrangler + D1 smoke test | Node tests + local D1 mock tests + Wrangler dry-run |
| Remote CPU evidence | None | None |

## Recommendation

Keep both prototypes unmerged for now. If choosing a direction for the next controlled validation stage, use the JavaScript Worker as the leading candidate because its current adapter has stronger explicit bounds around network calls, payload size/complexity, failure isolation, D1 grouped writes, and health freshness.

Do not treat this as a production approval. The JavaScript implementation duplicates provider parsing logic, so before it becomes authoritative the parser behavior must be compared against the existing Python fixtures and edge cases, and ideally moved into shared conformance fixtures to prevent drift.

The Python implementation remains valuable as the reference integration with the existing domain model. It should not be selected for unattended polling without adding equivalent HTTP timeout/body limits, robust per-provider failure isolation, atomic success writes, configuration validation, and request-time freshness calculation.

## Storage and retention

Retention is now specified in [QUOTE_DATA_RETENTION.md](QUOTE_DATA_RETENTION.md): keep BlackBit and Winance quote history for 30 rolling days; do not retain Money Storage or Sberkassa offer history, keeping only a replace-in-place current snapshot until the next successful refresh. The current prototype schemas and handlers do not yet enforce this policy: both still append observations indefinitely, and Money Storage/Sberkassa adapters are not implemented. This is a production blocker. At two historical providers polled every five minutes, the theoretical unpruned maximum is 576 observations/day or 210,240/year; this is a count estimate, not a measured D1 storage footprint.

## Remaining blockers

1. No Cloudflare deployment or remote CPU measurement has been authorized.
2. Workers Free Cron CPU budget must be verified with actual deployed telemetry; Node microbenchmarks and Wrangler dry-runs do not establish Cloudflare CPU time.
3. Money Storage authorized unattended cloud access remains unverified and disabled.
4. Sberkassa ERUB/RUB and RUB/USDT sources remain unavailable and unimplemented.
5. BlackBit remains indicative-only; its liquidity and execution are not verified.
6. `observed_at` is the Worker observation time, not an upstream exchange timestamp.
7. The 30-day BlackBit/Winance retention and current-only Money Storage/Sberkassa storage rules are specified but not yet enforced; no alerting channel is enabled.

## Safety

Read-only only. No trading, order placement, transfer, or account mutation code. No credentials or live account secrets are stored in this experiment. No deployment, Cron configuration, remote D1 creation, or merge is performed by this comparison.