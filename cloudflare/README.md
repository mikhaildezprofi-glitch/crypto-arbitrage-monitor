# Cloudflare Python Worker prototype

This is an isolated cloud runtime adapter for the existing read-only quote monitor. It does not deploy itself and does not require a phone, ADB, Termux, Polydev, or a local browser.

## What it currently does

- Runs as a Python Worker using Cloudflare's Pyodide runtime.
- Uses the Workers Fetch API for outbound HTTPS, not Python's urllib network client.
- Reuses the existing BlackBit and Winance response parsers and Quote model.
- Persists normalized observations and source health to D1.
- Polls only BlackBit ECR/USDT and Winance ERUB/USDT.
- Uses 300-second per-source intervals and rejects stale/future quotes.
- Exposes a read-only /health endpoint with source status only.
- Does not calculate a full route because Money Storage and both Sberkassa adapters are deliberately unavailable.
- Has no scheduled trigger configured yet.

The existing SQLite store is not used here: Cloudflare Python Workers have an ephemeral in-memory filesystem, and Python's threading module is non-functional in the Workers WebAssembly runtime. D1 is the durable storage layer for this adapter.

## Local validation

Requirements: Python 3.13+, uv, and Node.js 24+.

From the repository root:

    uv sync --project cloudflare
    uv run --project cloudflare pywrangler deploy --dry-run

The dry run compiles and packages the Worker without deploying it. CI runs this command on every relevant push and pull request.

For local runtime testing after configuring a real D1 database binding:

    cd cloudflare
    uv run pywrangler dev --test-scheduled

Then invoke the local scheduled handler:

    curl "http://localhost:8787/cdn-cgi/local/scheduled?cron=*/5+*+*+*+*"

Use local D1 state only for development. No production database is configured by this repository change.

## D1 setup (owner action required)

1. Create a D1 database in the owner's Cloudflare account.
2. Replace the all-zero placeholder database_id in wrangler.toml with the actual D1 database ID.
3. Apply the migration to the local development database:

       uv run pywrangler d1 migrations apply crypto-arbitrage-monitor --local

4. Run the local scheduled-handler test and verify rows in quote_observations and source_status.

Do not add a real account ID, API token, database credentials, or other secrets to Git. Do not deploy or create remote resources from CI.

## Free-plan constraint

Cloudflare currently documents 10 ms CPU per Cron Trigger invocation on Workers Free. Python Workers also execute through Pyodide. A local dry run does not establish that the scheduled handler fits the remote Free CPU limit. Do not enable a production Cron Trigger until a real remote benchmark proves it fits without paid usage.

## Known blockers

- Money Storage cloud access is not verified and remains disabled.
- Sberkassa ERUB/RUB and RUB/USDT adapters are not implemented.
- No complete five-source route can be calculated.
- No Telegram notification code is enabled.
- No Cloudflare account, D1 database, token, or deployment is connected to this repository.
- The placeholder D1 ID is intentionally nonfunctional until the owner creates a database.
