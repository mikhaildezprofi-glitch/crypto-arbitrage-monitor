# Cloud hosting options research

Research date: 2026-11-19

## Requirements

- Cloud-only execution; no phone, ADB, Termux, Polydev, or local browser.
- Read-only HTTPS collection, Decimal calculations, persistent normalized quote history, source health, and informational notifications.
- No provider-support outreach.
- No unexpected paid usage. Do not deploy or enable billing without an explicit owner decision.
- The full route remains disabled until all five data sources and fee rules are verified.

## Option A: GitHub Actions scheduled workflow

Official GitHub documentation states:
- Scheduled workflows run only from the default branch.
- The shortest supported schedule interval is five minutes.
- Scheduled runs can be delayed during high load, and queued jobs may be dropped.
- Scheduled workflows use the latest commit on the default branch.

Sources:
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
- https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax

Assessment:
- Suitable for CI, tests, controlled deployments, and low-criticality scheduled tasks.
- Not suitable as the sole source of truth for continuous arbitrage monitoring where timing and durable state matter.
- It does not provide a persistent local filesystem between independent jobs. A separate durable database would still be required.
- Keep GitHub Actions for CI and deployment automation, not as the production quote database or persistent browser.

## Option B: Cloudflare Workers Cron + D1

Official Cloudflare documentation confirms:
- Cron Triggers invoke a scheduled handler and can call third-party APIs.
- Python Workers support scheduled handlers and the Python Workers runtime.
- Python Workers can access D1 through a configured binding.
- Workers Free currently lists 100,000 requests/day, 10 ms CPU per Cron Trigger, 128 MB memory, and five Cron Triggers per account.
- D1 Free currently lists 500 MB maximum per database, 5 GB total account storage, 50 queries per Worker invocation, and 5 million rows read/day plus 100,000 rows written/day. D1 free-tier daily query limits are enforced; queries fail until the daily reset when a limit is exceeded.

Sources:
- https://developers.cloudflare.com/workers/configuration/cron-triggers/
- https://developers.cloudflare.com/workers/languages/python/
- https://developers.cloudflare.com/d1/examples/query-d1-from-python-workers/
- https://developers.cloudflare.com/workers/platform/limits/
- https://developers.cloudflare.com/d1/platform/limits/
- https://developers.cloudflare.com/d1/platform/pricing/
- https://developers.cloudflare.com/changelog/post/2026-09-01-d1-free-tier-limit-enforcement/

Assessment:
- Stronger fit for scheduled cloud execution and durable storage than GitHub Actions.
- The 10 ms CPU limit on Workers Free Cron invocations is a serious constraint for a Python Worker and must be benchmarked before choosing the free plan.
- A small JavaScript Worker may fit the CPU limit more comfortably, but duplicating the existing Python Decimal/business logic would create maintenance risk.
- No account, database, API token, deployment, or billing setting has been changed.

## Current decision

No production host is selected or deployed in this change.

Keep the Python one-shot Docker worker as a portable implementation and use GitHub Actions for CI. Before choosing a production scheduler, benchmark the same deterministic quote-collection and calculation workload against Cloudflare Workers Free limits and verify the persistent D1 workflow. Do not claim always-on operation until a real cloud deployment has passed a scheduled execution and persistence-recovery test.

Do not send provider-support requests. Do not enable Money Storage or Sberkassa polling from this hosting research.
