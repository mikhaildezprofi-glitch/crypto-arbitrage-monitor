# Cloudflare Python Worker prototype

This is an isolated cloud runtime adapter for the existing read-only quote monitor. It does not deploy itself and does not require a phone, ADB, Termux, Polydev, or a local browser.

## What it currently does

- Runs as a Python Worker using Cloudflare's Pyodide runtime.
- Uses the Workers Fetch API for outbound HTTPS, not Python's urllib network client.
- Reuses the existing BlackBit and Winance response parsers and Quote model.
- Currently appends BlackBit/Winance observations to D1; this is a known prototype gap. The approved design is one current snapshot per source, replaced on the next successful poll, with no history.
- Polls only BlackBit ECR/USDT and Winance ERUB/USDT.
- Prototype config now defaults to 900-second intervals; the allowed production range is 900 to 3600 seconds (15 minutes to 1 hour), with the exact interval still undecided. Rejects stale/future quotes.
- Exposes a read-only /health endpoint with source status only.
- Does not calculate a full route because Money Storage and both Sberkassa adapters are deliberately unavailable. Those sources must use replace-in-place current snapshots only, never quote history; see [QUOTE_DATA_RETENTION.md](../docs/QUOTE_DATA_RETENTION.md).
- Has no scheduled trigger configured yet.

The existing SQLite store is not used here: Cloudflare Python Workers have an ephemeral in-memory filesystem, and Python's threading module is non-functional in the Workers WebAssembly runtime. D1 is the durable storage layer for this adapter.

## Local validation

Requirements: Python 3.13+, uv, and Node.js 24+.

From the repository root:

    uv sync --project cloudflare
    uv run --project cloudflare pywrangler deploy --dry-run
    uv run --project cloudflare python scripts/vendor_core.py

The last command copies the shared `src/arbitrage_monitor` package into Cloudflare's `python_modules` bundle after Pywrangler has synchronized third-party dependencies. This avoids maintaining a second copy of the parsers and data models. Re-run it whenever the core package changes, after the next Pywrangler sync.

CI then applies the migration to local D1, starts Wrangler in local scheduled-test mode with deterministic mock quotes, invokes the scheduled handler, and verifies both source-health rows were persisted. The mock mode is disabled by default in wrangler.toml and is used only by the CI-created .dev.vars file.

For local runtime testing after configuring a real D1 database binding:

    cd cloudflare
    uv run pywrangler d1 migrations apply crypto-arbitrage-monitor --local
    uv run python scripts/vendor_core.py
    uv run pywrangler dev --test-scheduled

Then invoke the local scheduled handler:

    curl "http://localhost:8787/cdn-cgi/local/scheduled?cron=*/5+*+*+*+*"

Use local D1 state only for development. No production database is configured by this repository change.

## D1 setup (owner action required)

1. Create a D1 database in the owner's Cloudflare account.
2. Replace the all-zero placeholder database_id in wrangler.toml with the actual D1 database ID.
3. Apply the migration to the local development database:

       uv run pywrangler d1 migrations apply crypto-arbitrage-monitor --local

4. Run the local scheduled-handler test and verify one row per provider in current_quotes and corresponding rows in source_status.

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
## Scheduled handler binding detail

The Python Workers ABI requires the scheduled handler signature `scheduled(self, controller, env, ctx)`. The handler uses `self.env` for bindings, which is the WorkerEntrypoint binding interface; this also avoids relying on a nullable explicit `env` argument in the local Wrangler scheduled-event bridge. The handler fails closed if the D1 binding is unavailable.
