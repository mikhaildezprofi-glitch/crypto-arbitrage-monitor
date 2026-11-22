# Crypto Arbitrage Monitor: operations status

Snapshot date: 2026-11-23

This file consolidates the agreed project rules and the verified implementation state. It is not a claim that unattended production polling is live.

## Operating rules

- Cloud-only development and execution. Do not use the phone, Termux, ADB, Polydev, or a local browser.
- Free infrastructure only. Do not enable paid services, paid APIs, VPS instances, paid plans, or automatic paid fallbacks.
- READ-ONLY quote collection and arithmetic only. Never create/accept orders, deposit, withdraw, transfer, or move funds.
- Do not export, log, commit, or send passwords, cookies, OAuth codes, session tokens, authorization headers, or browser storage.
- Do not bypass CAPTCHA, E-ID, MFA, Cloudflare challenges, or device binding.
- Failed refreshes invalidate the current cycle. Never backfill with an older quote.
- Full route calculation is unavailable unless all five quotes are current, valid, correctly directed, and all required fee inputs are known.
- BlackBit is indicative only; its displayed ECR/USDT rate is not an execution guarantee.

## Route and calculation

1. Money Storage: USDT -> ECR.
2. BlackBit: ECR -> USDT (displayed `last_rate` only; indicative).
3. Winance: USDT -> ERUB (pair ID 18 / ERUB-USDT only).
4. Sberkassa: ERUB -> RUB.
5. Sberkassa: RUB -> USDT.

Starting reference amount: 1000 USDT.

Profit = final USDT - 1000 USDT. ROI = profit / 1000 * 100%.

All arithmetic is denominated in USDT. Do not label USDT as exact USD without a current USDT/USD conversion. Unknown fees must remain unknown, not silently become zero.

## Agreed source rules

### Money Storage: USDT -> ECR

- Use only the "Всем предлагают" tab (`/deals#tab-3`).
- The observed page request is `GET /public_deals/fetch?offset=0&limit=20&from=ECR&to=USDT`.
- Raw row direction `src_currency=ECR,dst_currency=USDT` maps to displayed USDT -> ECR.
- Preserve source order; average the first 20 matching offers, or all if fewer.
- Do not deduct the displayed commission.
- Freshness is confirmed when the newest returned offer `create_time` is no more than 900 seconds old relative to cloud runner UTC collection time. Exactly 900 seconds is accepted. Future, missing, invalid, or older timestamps fail closed.
- Offer age does not filter the first-20 average.
- Reuse only the page's own same-origin request/response. Do not send a second request after the page request; do not retry 401/403/429.

### BlackBit: ECR -> USDT

- Resolve exactly one ECR/USDT pair from `/site/currency_pairs`.
- Read only `last_rate` from the corresponding order-book endpoint.
- Ignore order-book levels, volumes, and liquidity. Mark the quote indicative.

### Winance: USDT -> ERUB

- Use ERUB/USDT pair ID `18` only.
- Reject conflicting pair identifiers and invalid/non-positive rates.
- The adapter permits an explicit polling interval from 900 to 3600 seconds. The overall hourly schedule is agreed; production workflow must set the intended cadence explicitly to 3600 seconds.

### Sberkassa: ERUB -> RUB

- Use only `/deals#tab-3`, "Всем предлагают".
- The exact page-originated request must establish `from=ERUB&to=RUB`; when per-row currency IDs are unavailable, the request metadata is the direction context.
- Use only `back_rate`; ignore `rate`.
- Average the first 20 correctly directed offers in source order, or all if fewer.
- Any invalid/non-finite/non-positive selected `back_rate`, or no matching offers, makes the quote unavailable.
- Freshness is confirmed when at least one correctly directed offer has `create_time` within the preceding 900 seconds. Future or invalid timestamps do not confirm freshness. Creation time does not filter the first-20 average.
- Ignore fees, amounts, reserves, volumes, limits, liquidity, and partial execution.

### Sberkassa: RUB -> USDT

- Read only the displayed/current RUB -> USDT rate from `/exchange`.
- The actual numeric source field and a successful-refresh freshness signal must be independently established on `/exchange`.
- Do not borrow timestamps from `/deals`. HTTP Date, Last-Modified, ETag, browser time, Age, and network timing alone do not prove quote freshness.
- If the page has one published rate, use that rate. If it has independent offers, use the agreed first-20 average only after the structure and direction are proven.

## Verified progress and evidence

### Money Storage

- A prior real browser run on the PR #8 line read 20 USDT -> ECR offers; reported average: `0.178908318`; freshness was confirmed by `create_time` within 900 seconds. This is historical evidence of one successful read, not proof that the current session remains valid.
- Run `45040162913` later restored/decrypted a profile and saved an encrypted AES-256 profile cache. The browser returned to `storage.money/html/oauth_return.html` with HTTP 200, but E-ID state was `AUTHENTICATION_REQUIRED`; E-ID API received a Cloudflare 403 challenge. This did not prove authenticated quote access.
- A return URL or HTTP 200 by itself is never treated as authentication.
- The PR #9 bridge's normal mode reads the page-originated offers response and separates authentication confirmation from quote freshness.
- Current browser startup is deliberately session-first: open `/deals#tab-3` using the restored profile; only if the protected page rejects the session does the bridge navigate to the normal account/E-ID flow. This avoids forcing OAuth on every run.
- The latest PR #9 code changes have passed the repository unit suite: Actions run `45058948246`, commit `55c793e792f1c7b3907c65ca52608fda6d94177e`, 121 tests passed. This is code/CI evidence, not a new live provider run.

### Sberkassa

- Earlier authenticated inspection observed 27 `back_rate` fields for ERUB -> RUB, but freshness was not confirmed.
- The sanitized probe and pure quote helper are implemented. The helper is not evidence of a current live quote.
- No verified numeric RUB -> USDT rate plus independent `/exchange` freshness signal has been established.
- Therefore neither Sberkassa leg is cleared for scheduled full-route calculation.

### BlackBit and Winance

- Read-only adapters and parser tests exist.
- Current production workflow does not yet provide a complete five-source live validation record for both adapters.
- Synthetic/unit tests are not proof of live quote retrieval or provider freshness.

## Current repository state

- PR #7: open; encrypted Chromium profile persistence.
- PR #8: open Draft; Sberkassa diagnostics and freshness rules.
- PR #9: open Draft; original Money Storage E-ID/session work. Its branch diverged from the current PR #8 head and is superseded by PR #10 for integration review.
- PR #10: open Draft; integration branch based directly on the current PR #8 head `f13c8f0b09e11cf3888828cf2920c274e058409f`, with the PR #9 Money Storage changes ported and the precise Cloudflare classifier/top-level document fixes retained.
- PR #10 head at this snapshot: `0d2e45b499ab4219900196d824c10c475accf320`; it is mergeable but not merged. Do not merge until live source validation and CI are complete.
- The repository `main` branch still contains stale README wording that conflicts with the newer Money Storage `create_time` freshness rule.
- No hourly production schedule is enabled.
- The existing `four-step-quote-test.yml` is a manual diagnostic and intentionally does not calculate final USDT, profit, or ROI. It omits the fifth source.

## Automation target

- One report per hour from 09:00 through 02:00 Astana time (Asia/Almaty, UTC+5), including both ends: 18 runs/day.
- Equivalent GitHub Actions cron: `0 4-21 * * *` UTC.
- One report must show all five route legs, direction, rate, collection time, freshness/status, and a clear reason for every unavailable source.
- Calculate final amount, profit, and ROI only when all five legs are fresh and valid and fee inputs are known. Otherwise explicitly mark the full route unavailable.
- No previous-cycle quote may be substituted.
- Delivery destination is not yet configured. Telegram must not be assumed configured.

## Hard blockers before enabling the schedule

1. Prove Money Storage session reuse in normal quote mode on a fresh runner, including exact request parameters, HTTP 200, `result=ok`, correct pair, newest `create_time`, and a normalized quote. The latest E-ID challenge means this is not currently proven.
2. Validate Sberkassa ERUB -> RUB direction, `back_rate` average, and 15-minute `create_time` freshness from a fresh authenticated capture.
3. Find and validate the numeric RUB -> USDT field and an independent successful-refresh freshness signal on `/exchange`.
4. Run live checks for BlackBit and Winance and confirm their response semantics and freshness handling.
5. Wire all five providers into one collector/report. The current manual diagnostic only collects four.
6. Resolve fee inputs or keep net final amount/profit/ROI unavailable. Never assume unknown fees are zero.
7. Decide a notification destination and implement it without exposing secrets.
8. Reconcile PR #7 -> PR #8 -> PR #9 into one tested default-branch version before enabling a schedule.

## Free-runtime constraint

The repository is private. GitHub documents included compute usage for private-repository Actions and bills usage beyond the included allowance; standard runners in public repositories are free. The current interactive browser workflow has long timeouts, VNC/tunnel setup, browser installation, and a separate restored-session verification job. Running that design 18 times daily is not a safe assumption under the free-only requirement.

The scheduled design must therefore be a separate, minimal headless read-only job that restores an already authenticated encrypted profile, performs no VNC/tunnel or interactive login, does not run the separate session-verification job every hour, and fails closed when the session is rejected. Measure actual minutes before enabling the 18-run/day schedule. Do not add a paid fallback.


## Additional verification recorded on 2026-11-23

- Money Storage browser run `45057434501` restored and decrypted the encrypted Chromium profile successfully, but the protected account route returned HTTP 401 repeatedly. The bridge entered the ordinary `storage.money/login` route and E-ID login page. The E-ID page showed a Cloudflare challenge-platform request and required a fresh interactive sign-in. No authenticated offers response was captured; no quote artifact or new encrypted profile was saved. This is a confirmed session rejection, not an OAuth success.
- This run proves that the current saved profile is not sufficient for unattended Money Storage access at that point in time. It does not justify retrying the same E-ID flow repeatedly or bypassing Cloudflare.
- A replacement integration branch was created from the current PR #8 head and the PR #9-specific files were ported as one integration commit. PR #10 is the review surface; PR #9 remains open but superseded.
- The latest PR #10 test workflow run `45073521252` failed before any job step was allocated (GitHub reports an empty step list and no runner ID). This is not evidence of a unit-test assertion failure. Earlier PR #9 head `55c793e792f1c7b3907c65ca52608fda6d94177e` did complete all 121 unit tests successfully in run `45058948246`. The newer classifier changes still require a real CI execution on an allocated runner.
- The PR #10 branch has an updated README reflecting the agreed Money Storage `create_time` freshness rule, explicit fifth-source blocker, session-reuse limits, and disabled schedule.
- The five-source collector data model exists, but the production workflow remains a four-source diagnostic. The Sberkassa `/exchange` probe records candidate fields only; no provider is allowed to turn those candidates into a valid RUB -> USDT quote yet.
