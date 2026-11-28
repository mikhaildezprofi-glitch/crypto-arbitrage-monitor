# Crypto Arbitrage Monitor: operations status

Snapshot date: 2026-11-28

This file consolidates the agreed project rules and the verified implementation state. It is not a claim that unattended production polling is live. Historical dated notes below may describe earlier decisions; the current decisions immediately below take precedence.


## Current decisions (2026-11-28; supersede earlier notes)

- The only development branch is `work/sberkassa-chromium-integration-20261128`; `main` is updated only through a reviewed, passing pull request. No additional branches are to be created.
- All five route-fee defaults are temporarily `0%` during collector development. This is a placeholder, not a claim about actual provider fees. Ignore provider-displayed commissions. After all collectors work, configure manual fees in the calculator. Until then, report route results as pre-fee estimates, not net profit.
- Starting capital is not fixed at 1000 USDT; it must remain configurable and no default amount is assumed.
- Intended cadence remains hourly from 09:00 through 02:00 Asia/Astana (`0 4-21 * * *` UTC), but recurring workflows remain disabled until all five live sources are validated and free-runner cost is measured. Collection workflows are manual-only during development.
- Previous live checks exist for Money Storage, BlackBit, Winance, and Sberkassa ERUB -> RUB. The new GET-only enforcement for Money Storage and Sberkassa quote endpoints requires a fresh read-only run. Sberkassa RUB -> USDT still requires confirmation of the actual displayed rate and independent successful-refresh freshness signal.
- Keep the four-source workflow only as an explicitly manual diagnostic that ends at RUB; it must not be presented as a complete arbitrage route.
- The fixed-cache profile export workflow tied to an old branch/run was removed. The current shared-browser workflow owns profile persistence.


## Current implementation and validation (2026-11-28)

- `run_full_collection.py` now connects the five providers to `five_step_route` and the Decimal calculator. It evaluates only a complete set of five fresh quotes, uses a normalized 1 USDT basis (not an assumed starting capital), and reports a pre-fee estimate. It never labels the result net profit; the five 0% fee values are temporary placeholders.
- The collection workflow now fails when browser collection fails, a required artifact is missing, any quote is stale, or route validation fails. It uploads a sanitized report for diagnosis even when route validation fails.
- Money Storage's quote endpoint and Sberkassa's protected quote requests enforce GET-only collection. Non-GET requests are blocked; there is no POST fallback. If a provider requires POST to expose its read-only quote, that source remains unavailable.
- Sberkassa ERUB -> RUB averages the first 20 correctly directed offers, or all available if fewer than 20. At least one valid offer is required, and the newest qualifying `create_time` must be within 900 seconds.
- The authenticated-profile save gate no longer incorrectly depends on a quote-collection marker. It saves only after the shared authentication probe confirms all three protected tabs.
- Runtime Python dependency is `websocket-client`, declared in `pyproject.toml` and verified by CI. Playwright is used only to download the Chromium binary in the browser workflow; the browser session is driven through CDP.
- All remaining scripts have identified callers in workflows or imports. The obsolete standalone Winance-only polling module was removed because the five-source collector and external scheduler supersede it. The inactive `WINANCE_POLL_SECONDS` setting and stale `.env.example` entries (including the old 1000 USDT capital default and unused direct Money Storage endpoint settings) were removed. Money Storage's 900-second constant is now named for freshness, not polling.
- **Approved browser architecture:** one shared Chromium process and one encrypted profile with exactly three protected tabs: Money Storage, Sberkassa Deals, and Sberkassa Exchange. BlackBit and Winance are collected separately through public HTTPS GET APIs, not browser tabs. This three-tab architecture is the accepted project requirement.
- CI passed on the immediately preceding code revision: 158 unit tests, project/dependency installation, WebSocket client verification, runner clock check, shell syntax validation, and actionlint workflow validation (run `46173423234`). No end-to-end live five-source collection has yet passed.
- No Oracle VM deployment, recurring schedule, notification channel, or production collection has been enabled. The agreed schedule remains hourly 09:00-02:00 Asia/Astana, disabled until live acceptance and free-runtime measurement.
- PR #34 remains open. The three-tab Chromium architecture is accepted. Do not merge until live source behavior and end-to-end five-source route reporting are validated.

## Historical notes (superseded; retained for traceability)

The sections below record earlier investigations and decisions. Where they conflict with the current decisions and implementation above, they are historical only. Use the current README and the current sections at the top of this document for active requirements.

### Historical operating rules

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
- Winance is fetched once per collection cycle; cadence belongs to the external scheduler. The agreed target is hourly (3600 seconds), but recurring execution remains disabled until live integration acceptance.

### Sberkassa: ERUB -> RUB

- Use only `/deals#tab-3`, "Всем предлагают".
- The exact page-originated request must establish `from=ERUB&to=RUB`; when per-row currency IDs are unavailable, the request metadata is the direction context.
- Use only `back_rate`; ignore `rate`.
- Require at least 20 correctly directed offers; average exactly the first 20 in source order. Fewer than 20 makes the quote unavailable.
- Any invalid/non-finite/non-positive selected `back_rate`, or no matching offers, makes the quote unavailable.
- Freshness is confirmed when at least one correctly directed offer has `create_time` within the preceding 900 seconds. Future or invalid timestamps do not confirm freshness. Creation time does not filter the first-20 average.
- Ignore fees, amounts, reserves, volumes, limits, liquidity, and partial execution.

### Sberkassa: RUB -> USDT

- Read only the displayed/current RUB -> USDT rate from `/exchange`.
- The actual numeric source field and a successful-refresh freshness signal must be independently established on `/exchange`.
- Do not borrow timestamps from `/deals`. HTTP Date, Last-Modified, ETag, browser time, Age, and network timing alone do not prove quote freshness.
- If the page has one published rate, use that rate. If it has independent offers, use the agreed first-20 average only after the structure and direction are proven.

- A separate manual workflow-dispatch target, `sberkassa_exchange`, and probe `scripts/sberkassa_exchange_chromium_probe.py` are implemented for discovery. It reuses the shared encrypted Chromium profile, opens only `/exchange`, does not click or change page controls, and blocks every non-GET request to Sberkassa.
- The discovery artifact contains sanitized visible quote-related lines, selected currency controls, allowlisted numeric quote/time fields from same-origin JSON responses, response status/cache metadata, and browser response timing for correlation. It does not publish raw bodies, cookies, authorization headers, tokens, or general input values.
- Initial discovery capture is limited to five minutes. This is not quote validation: no RUB -> USDT field, direction, or successful-refresh freshness signal is accepted until independently established from the captured evidence.

- Live discovery run `45701204557` confirmed an authenticated HTTP 200 load of `/exchange`, but its first sanitized capture did not identify a quote. A follow-up run `45702982406` found the custom SelectBoxIt currency controls and the page's `current_rate` region. The default selection was E-Ruble -> RUB, and the page text stated that this pair is not quoted; this is not the required RUB -> USDT direction.
- The page-originated `GET /api/get_wallets` returned HTTP 200. The exchange form uses hidden `src_wallet_id` / `dst_wallet_id` selects rendered through custom controls. The current discovery pass is being extended to record only safe currency option labels, never wallet IDs, balances, or arbitrary form values.
- The page's public scripts expose currency selectors such as `#currency_from`, `#currency_to`, and `#current_rate`. A deal-creation endpoint is present in the site script but is excluded from discovery and must never be called.
- No RUB -> USDT rate, provider quote timestamp, or successful-refresh freshness signal has been established. Do not change the currency selection or submit any form until the user explicitly approves a quote-only selection change; never press the exchange/create button.

- Public source inspection (2026-11-25) confirms `/js/convert.js` does not request a quote when a currency changes. Its `change` handler reads the already-loaded global `rates` matrix at `rates[to.currency_id][from.currency_id]` and renders the result in `#current_rate`. Thus the quote is calculated client-side from data supplied with the page, not fetched on each dropdown click.
- Public `/js/system.js` confirms `GET /api/get_wallets` populates the wallet store and the currency selects. The `#exchange` form submit handler separately sends `POST /action/exchange`, then opens an exchange-confirmation dialog. This endpoint is transaction-initiating and is explicitly out of scope; never submit the form or confirm the dialog.
- The user explicitly authorized clicking only the RUB and USDT currency dropdowns/options to inspect the displayed pair. A revised probe now clicks those two controls through the actual SelectBoxIt UI, enters no amount, and never clicks the form submit button. The network interceptor continues to block all non-GET requests to Sberkassa. It records only currency codes, the RUB -> USDT matrix value, and the displayed rate text; wallet IDs, balances, and arbitrary form values are excluded.
- A successful local display after selecting the pair is not by itself a provider freshness signal. The matrix source and any quote-update timestamp/refresh event still need separate validation before accepting the quote.
- The existing ERUB -> RUB deals collector remains separate and unchanged. Do not merge PR #10 or enable full-route calculations from this discovery probe.

## Verified progress and evidence

### Money Storage

- A prior real browser run on the PR #8 line read 20 USDT -> ECR offers; reported average: `0.178908318`; freshness was confirmed by `create_time` within 900 seconds. This is historical evidence of one successful read, not proof that the current session remains valid.
- Run `45040162913` later restored/decrypted a profile and saved an encrypted AES-256 profile cache. The browser returned to `storage.money/html/oauth_return.html` with HTTP 200, but E-ID state was `AUTHENTICATION_REQUIRED`; E-ID API received a Cloudflare 403 challenge. This did not prove authenticated quote access.
- A return URL or HTTP 200 by itself is never treated as authentication.
- The integrated PR #10 bridge's normal mode reads the page-originated offers response and separates authentication confirmation from quote freshness.
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
- PR #9: closed as superseded; do not merge.
- PR #10: open Draft; integration branch based on PR #8, with the Money Storage session work ported and the Cloudflare classifier/top-level document fixes retained.
- PR #10 head at this snapshot: `8054990b44c291f9d8f85776aecbad4798779e69`; it is mergeable but not merged. Keep it Draft until live source validation is complete.
- The integration branch README now reflects the public repository state and agreed quote rules. `main` remains unchanged until a reviewed merge.
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


## Verification recorded on 2026-11-25

- Repository visibility was changed to Public and independently confirmed through the GitHub repository API (visibility=public).
- PR #10 was corrected so restored-session verification no longer treats a protected page HTTP 200 as sufficient. It now requires three independent fresh Chromium processes, each reading the page-originated Everyone Offers response and validating the USDT -> ECR pair, normalized quote, and provider create_time freshness window of 900 seconds.
- Added a unit test that guards this three-process, real-offers verification contract.
- CI run 45681563302 passed all 127 unit tests. Its runner clock check also passed using three responding HTTPS Date references. Earlier runs failed because of stale documentation assertions and an unsuitable GitHub API Date reference; both issues were corrected.
- This CI result is unit-test evidence only. It does not establish a currently valid Money Storage session or a live quote.
- No new E-ID browser workflow was dispatched. The last live inspection showed the saved profile was rejected and required a normal interactive E-ID/Cloudflare flow. The next live step requires the owner's participation in that flow and a configured CHROMIUM_PROFILE_PASSPHRASE secret.
- PR #7 remains open and non-Draft; PR #8 and PR #10 remain open Drafts. No PR was merged. No hourly schedule or Telegram delivery was enabled.


## Latest verified state (2026-11-26; supersedes earlier status where noted)

### Money Storage session reuse
- Interactive browser workflow run `45688839011` completed successfully on 2026-11-25.
- The encrypted Chromium profile was restored and decrypted in a separate job.
- Three independent Chromium processes each read the real page-originated Everyone Offers response for USDT -> ECR, validated 20 offers, and passed the provider `create_time` freshness rule (newest offer ages: 10.9, 9.2, and 40.4 seconds).
- Each attempt reported `MONEY_STORAGE_SESSION=AUTHENTICATED_AFTER_PROTECTED_READ`. The second attempt succeeded after the 120-second cooldown added for HTTP 429 handling.
- This supersedes the earlier statement that no current authenticated session had been confirmed. The saved profile is reusable while the provider continues to accept it; session expiry/revocation or a new provider challenge may still require normal user authentication.

### BlackBit live validation
- Added `scripts/validate_blackbit_live.py` and the isolated `.github/workflows/blackbit-live-check.yml` workflow.
- BlackBit adapter requests now include `Cache-Control: no-cache` and `Pragma: no-cache` to request revalidation rather than reuse an intermediary cached response.
- Live workflow run `45690240533` completed successfully on the integrated branch. It resolved exactly one ECR/USDT pair (ID `6`), read only `last_rate`, and returned `1.311` at `2026-11-25T19:57:32.262185Z`.
- The endpoint does not expose a quote timestamp. The recorded `observed_at` therefore means the UTC time of successful live HTTPS retrieval, not an independently published market-update timestamp. This limitation is explicit in the live report; no order-book levels, volumes, liquidity, or execution checks are used. The quote remains indicative only.
- Unit test run `45690234316` passed all 127 tests, including the new cache-revalidation header assertions.

### Remaining blockers
1. Validate Winance through a live read-only retrieval of pair ID 18 and confirm the response semantics.
2. Validate Sberkassa ERUB -> RUB direction, first-20 `back_rate` average, and 15-minute `create_time` freshness from a fresh authenticated capture.
3. Identify and validate the Sberkassa RUB -> USDT numeric field and an independent successful-refresh freshness signal on `/exchange`.
4. Complete one integrated five-source report. The current four-source diagnostic still intentionally omits the fifth source and cannot report final USDT, profit, or ROI.
5. Confirm fee inputs or keep net final amount/profit/ROI unavailable. Unknown fees remain unknown.
6. Select and implement a notification destination without exposing secrets.
7. Measure free GitHub Actions runtime before considering the 18-runs/day hourly schedule. No recurring schedule or Telegram delivery is enabled.

PR #10 remains Draft and unmerged. The Money Storage and BlackBit live validations do not clear the remaining Winance/Sberkassa blockers.


### Winance live validation
- Added `scripts/validate_winance_live.py` and the isolated `.github/workflows/winance-live-check.yml` workflow.
- The adapter now requires the successful API envelope (`result=ok`, `status=200`) and requests cache revalidation with `Cache-Control: no-cache` and `Pragma: no-cache`.
- Live workflow run `45690618669` completed successfully. It confirmed exactly pair ID `18`, `ERUB/USDT`, displayed rate `0.032728`, retrieved at `2026-11-25T19:59:57.829592Z`.
- The endpoint does not publish a quote timestamp. The recorded `observed_at` is the UTC retrieval time from the live HTTPS response, not an independently published market-update timestamp.
- Unit-test run `45690807145` passed all 129 tests, including the Winance response-envelope and cache-revalidation tests.


## Current verified status after Sberkassa live run (2026-11-25)

- Live-validation code commit: `cc6969e088b2c73fb0d8cd710f36974f054a26d0`. PR #10 remains Draft and unmerged.
- Sberkassa ERUB -> RUB was live-validated by Actions run [45697596726](https://github.com/mikhaildezprofi-glitch/crypto-arbitrage-monitor/actions/runs/45697596726).
- The encrypted shared Chromium profile was restored, the existing authenticated Sberkassa session was reused, and the updated profile was encrypted and saved back to GitHub Actions Cache.
- The collector opened only `/deals#tab-3`. It set the read-only page filter to `currency_from=ERUB` and `currency_to=RUB` before page scripts initialized, disabled browser cache, and blocked `/exchange` plus any public-deals request with another direction.
- The page-originated `GET /public_deals/fetch?from=ERUB&to=RUB` returned HTTP 200 and 50 offers. Exactly the first 20 `back_rate` values were averaged: `41.824849917`. An independent recomputation from the sanitized artifact matched exactly.
- The newest qualifying server `create_time` was 31.7 seconds old at capture. The 15-minute freshness check passed.
- Sanitized artifact `sberkassa-current-inspection`, ID `15061472918`, was uploaded successfully. No raw response body, cookies, or session tokens were published.
- Unit-test run [45697606894](https://github.com/mikhaildezprofi-glitch/crypto-arbitrage-monitor/actions/runs/45697606894) passed all 134 tests.
- This clears only Sberkassa ERUB -> RUB. RUB -> USDT remains uncollected and is outside the current deals-only scope; do not open `/exchange`. The five-source report, fee inputs, notification destination, and free-runner cost still require work. No recurring schedule or fund-moving operation is enabled.
