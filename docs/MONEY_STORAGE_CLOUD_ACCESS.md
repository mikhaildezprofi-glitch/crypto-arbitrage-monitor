# Money Storage cloud access decision

## Status

Live cloud polling is **blocked** until Money Storage provides a supported server-side read-access method.

The repository contains a pure parser, quote builder, and a configurable HTTPS read-only provider (`MoneyStorageQuoteProvider`). The provider requests only `offset=0&limit=20`, requires explicit `from`/`to` filters, validates the `result=ok` response envelope, and fails closed on HTTP/auth/rate-limit errors. It does not support browser cookies, session tokens, or credentials. It has not yet been demonstrated to retrieve live offers from the cloud. The frontend JavaScript exposes the public-deals route:

- `GET /public_deals/fetch`
- Query fields used by the frontend: `offset`, `limit`, `from`, `to`
- The frontend reads the offers from the response `data` field.

Prior direct unauthenticated tests of this route returned HTTP 401. A subsequent repeat returned HTTP 429. These observations are not a basis for retrying, bypassing access controls, or treating the endpoint as a public cloud API. No official server-to-server API documentation or supported machine credential flow has been identified in the current research.

## Required access before implementation

Obtain from Money Storage support or official documentation:

1. Confirmation that automated server-side read access to public offers is supported.
2. The official API base URL and exact query parameter semantics, including the currency filters corresponding to the displayed "Мне предлагают" USDT -> ECR direction.
3. The supported authentication method for a server workload, if authentication is required.
4. Rate limits and polling guidance, including whether a 15-minute interval is permitted.

Do not use browser cookies, session tokens, OAuth authorization codes, browser storage, or copied authorization headers as cloud credentials. Do not spoof device identity, bypass MFA/CAPTCHA/device binding, or retry around HTTP 429.

## Required quote behavior after access is approved

- Request only the first page: `offset=0`, `limit=20`.
- Parse only raw ECR/USDT records that represent the displayed USDT -> ECR offers.
- Preserve response order and calculate the arithmetic mean of the first 20 available target-direction `rate` values.
- If fewer than 20 matching offers are returned, average the available matching offers. If none are returned, mark the source unavailable.
- Do not sum offer amounts, select a best offer, infer partial fills, or simulate an order.
- The displayed commission is paid by the seller when accepting an offer in this direction; retain it as source metadata but do not deduct it from this route step.
- Timestamp the resulting quote at successful observation time, not at offer creation time.
- Reject non-success HTTP responses, malformed payloads, wrong currency direction, non-positive/non-finite rates, and empty results.
- Never substitute a previous quote after a failed poll.

## Scheduling and persistence

Do not enable a scheduled job while the endpoint cannot be accessed from the cloud. The provider deliberately makes one request per call and does not retry 401/429. A cron job that repeatedly receives access errors is not live quote monitoring. The `MONEY_STORAGE_FROM` and `MONEY_STORAGE_TO` filters are intentionally blank in `.env.example` until their exact values for the desired UI direction are confirmed.

Once access is approved, implement a cloud polling worker at 900-second intervals, persist the latest quote and observation timestamp, expose explicit source health/error state, and feed only fresh quotes into the route collector. Keep credentials in the cloud provider's secret store and out of repository files, Telegram messages, and logs.

## Acceptance checks

- A cloud-run integration test can retrieve the first page using the officially supported access method.
- Unit tests cover the first-20 arithmetic mean, fewer-than-20 behavior, empty results, wrong pair, malformed payload, HTTP/auth errors, and timestamping.
- An unsuccessful poll leaves the source unavailable; it does not publish a stale quote as fresh.
- The full route remains unavailable whenever this required source is unavailable or stale.

## Transport milestone (2026-11-18)

A real phone-to-cloud HTTPS smoke test has passed:

- The Samsung/Termux client sent a test-only JSON payload over HTTPS through a temporary Cloudflare tunnel.
- The one-use cloud receiver validated the payload and returned HTTP 200 with a SHA-256 digest.
- GitHub Actions confirmed `PHONE_TO_CLOUD_HTTPS_TEST=PASS`.
- Workflow run: https://github.com/mikhaildezprofi-glitch/crypto-arbitrage-monitor/actions/runs/44260981536

This proves that the phone can reach a temporary cloud HTTPS receiver. It does **not** prove Money Storage authentication, quote retrieval, or a persistent production transport. No Money Storage cookies, OAuth codes, session tokens, or account data were transferred.

## E-ID OAuth investigation (2026-11-18)

The observed Money Storage login flow is an OAuth authorization-code redirect:

- Authorization entry point on the relying party: `https://storage.money/oauth/authorize/eid`
- Identity-provider authorization page: `https://e-id.cards/oauth/user`
- Client identifier observed in the Money Storage authorization request: `moneystorage`
- Redirect URI observed in the request: `https://storage.money/oauth/callback/eid`
- Requested profile scopes observed: `firstname surname email phone`
- Response type: `code`

This confirms an authorization-code style browser login, but it does **not** establish a supported server-side OAuth integration. Publicly discoverable material reviewed for this investigation did not document the E-ID token endpoint, client authentication method, token lifetime/refresh behavior, PKCE requirements, or whether the `moneystorage` client is permitted to exchange authorization codes from an independent cloud callback. The public E-ID agreement describes the Agent/User relationship but does not publish an API integration specification.

Do not guess token endpoint paths, attempt undocumented token exchanges, or reuse an authorization code captured from a browser. The observed redirect URI belongs to Money Storage; changing it to a cloud callback would require the relying party/E-ID client registration to explicitly allow that redirect URI. A standard OAuth authorization-code flow cannot be completed safely from the authorization URL alone.

### Current decision

- Keep the existing unauthenticated provider disabled for production polling; it has already returned 401 and 429.
- Do not add cookie/session-token ingestion or browser fingerprint emulation.
- The next required technical input is an official E-ID/Money Storage integration specification or confirmation from their support of: token endpoint, client authentication, allowed redirect URI registration, PKCE policy, refresh-token policy, and server-side use permission.
- Once those are confirmed, implement a dedicated OAuth client using a cloud callback and secret storage. Store tokens only in the cloud secret store, redact them from logs, and keep the existing first-20 offer parser and 900-second polling logic unchanged.

## Important identity-provider distinction (2026-11-18)

A search found a separate public OAuth SSO specification at `docs.e.id`. It documents a v1.1 server-side token exchange at `POST /api/v1.1/oauth/get-token` with `client_id`, `client_secret`, `code`, and `redirect_uri`, and describes client registration with an exact callback URL.

However, Money Storage's observed login redirects to the distinct hostname `e-id.cards`, not `e.id`. The public `docs.e.id` specification uses `api-dev.e.id` / `api-wallet.e.id` and does not establish that `e-id.cards` is the same identity provider, shares its API, or accepts the Money Storage OAuth client. Search results and the accessible `e-id.cards/login` page did not expose a matching token-exchange specification or OpenID discovery document.

Therefore the `docs.e.id` token endpoint is **not** to be called with the observed `moneystorage` client ID, and no OAuth code or credentials should be sent to it. Treating similarly named domains as one provider would be an unsafe integration assumption.

### Verified conclusion

- The Money Storage authorization-code redirect is observed.
- A generic server-side OAuth code-exchange pattern exists for a separately documented e.id service.
- A supported token exchange for the actual `e-id.cards` identity provider remains unverified.
- The exact `e-id.cards` issuer metadata, authorization/token endpoints, client registration rules, and redirect URI policy must be supplied or confirmed by that provider / Money Storage.
- Until then, do not implement a token client, do not change the existing provider, and keep live Money Storage polling disabled.
