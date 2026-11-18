# Authorized read-only bot access: Money Storage and Sberkassa

## Goal

Run a cloud-side monitor that can keep the owner's authorized Money Storage and Sberkassa pages/data refreshed, read published offers and rates, and feed the five-step calculator. The required Money Storage view is **only "Всем предлагают"**. The "Мне предлагают" view is out of scope. The Money Storage displayed commission is ignored and is never deducted from the route.

This document describes read-only collection. It does not authorize creating, accepting, editing, or cancelling deals, sending transfers, deposits, or withdrawals.

## What the current E-ID handoff does and does not do

`.github/workflows/browserless-eid-handoff.yml` starts a temporary Chromium session on an ephemeral GitHub Actions runner. It lets the account owner complete the normal E-ID flow in that browser. The tunnel is protected by a long random HTTP Basic Auth password in front of noVNC, in addition to the VNC password. Connection details are stored in a private-repository artifact with one-day retention.

This is a **manual, temporary login diagnostic**, not a persistent bot login:
- The runner is temporary and the workflow ends.
- The browser context is not configured as durable storage.
- Authentication cookies/session state are not exported or persisted.
- A successful redirect to `/account` only confirms navigation; it does not prove that API requests for offers or rates are available.
- The workflow must not be used as a permanent browser endpoint or left running as a substitute for a service.

## Required production architecture

1. **Dedicated cloud worker**, not a GitHub Actions job. Run it as a small managed service with a private network boundary and explicit lifecycle.
2. **Owner-controlled login.** The account owner completes the provider's ordinary E-ID/MFA/CAPTCHA flow in the approved browser. The bot must not bypass or automate around those controls.
3. **Provider-approved session use.** Before reusing a browser session or calling authenticated endpoints from a server, confirm that Money Storage and Sberkassa permit automated read-only access and that the account/session method is allowed. Prefer an official server-to-server API or OAuth client where available.
4. **Protected session storage.** If the provider explicitly permits persistent browser sessions, store the browser state only in encrypted cloud storage/KMS, scoped to the worker identity. Never commit it, put it in GitHub artifacts, send it to Telegram, or expose it to ChatGPT/Polydev logs. Restrict access, rotate/revoke on demand, and redact request headers and response bodies that may contain personal data.
5. **Read-only collection.** Use only the normal UI's observed requests and documented read endpoints. Money Storage reads the first page of "Всем предлагают" (20 rows, raw `src=ECR,dst=USDT`, displayed USDT -> ECR). Ignore its displayed commission. Sberkassa requires two independently verified read paths: ERUB -> RUB and RUB -> USDT.
6. **Polling and freshness.** Money Storage target interval is 900 seconds. Other intervals must follow provider limits and actual freshness evidence. Respect 401, 403, 429, Retry-After, and provider terms. Do not retry around rate limits or access controls. A failed poll marks that source unavailable; never reuse stale data as fresh.
7. **Audit and alerting.** Store only normalized quote fields, observation time, source health, and redacted error categories. Keep secrets and raw authenticated payloads out of logs. Notify the owner when reauthentication is needed.
8. **No transaction actions.** The production worker exposes no create/accept/cancel/transfer endpoints. It only reads listings/rates and calculates indicative results.

## Provider facts still required

### Money Storage
- Confirm from provider/support that cloud-side automated read-only access is allowed.
- Confirm a supported server authentication method or approved persistent browser-session method.
- Confirm rate limits and whether 15-minute polling is permitted.
- The only in-scope UI is "Всем предлагают"; never query or calculate from "Мне предлагают".
- Ignore commission in this project's Money Storage calculation.

### Sberkassa
- Complete owner-authorized inspection of both exact UI directions: ERUB -> RUB and RUB -> USDT.
- Confirm the real host, request method/path, required parameters, response schema, displayed-rate meaning, limits, fees, timestamps, and polling limits.
- Confirm whether automated cloud read-only access is allowed and how the account should authenticate.
- Do not substitute `erub.site` endpoints or another service's API.

## Go-live conditions

Do not enable continuous polling until:
- both providers' automated access is confirmed as permitted;
- the authenticated read paths and schemas are verified;
- session storage and worker access controls are in place;
- tests cover expiry, 401/403, 429/Retry-After, malformed data, empty listings, stale quotes, and reauthentication;
- all transaction-capable actions are absent from the worker.

The next technical milestone is to obtain the sanitized, owner-authorized Chrome Network observations for "Всем предлагают", Sberkassa ERUB -> RUB, and Sberkassa RUB -> USDT, then implement only the verified read-only adapters.
