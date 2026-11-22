# Money Storage cloud access decision

## Current status (2026-11-22)

A **manual, one-shot read-only quote capture** is implemented in the owner-authenticated cloud Chromium workflow. Scheduled cloud polling remains **blocked** until Money Storage confirms an approved unattended server-side access method and the complete five-source route is validated.

The normal browser workflow:
- Opens `https://storage.money/deals#tab-3` in a temporary cloud Chromium session.
- Leaves E-ID, CAPTCHA, MFA, Cloudflare and device-binding steps to the account owner.
- After the E-ID callback lands on `/account`, returns to `/deals#tab-3`.
- Passively captures the page's own same-origin Fetch/XHR response from `GET /public_deals/fetch`. It does not issue a second request, alter the original request, or export browser credentials.
- Reads the captured response in memory and validates its exact origin, path, query, HTTP status, JSON envelope and currency direction.
- A protected `result=ok` response confirms the browser session; quote freshness is checked separately.

### Confirmed frontend request

```http
GET https://storage.money/public_deals/fetch?offset=0&limit=20&from=ECR&to=USDT
```

The raw records use `src_currency=ECR` and `dst_currency=USDT`, corresponding to the displayed user direction USDT → ECR.

### Quote calculation and freshness

- Preserve the original response order and calculate the arithmetic mean of the first 20 correctly directed offers (or all matching offers if fewer than 20 are returned).
- Use the provider's `create_time` values for freshness. The newest correctly parsed offer must be no older than 900 seconds at collection time; exactly 900 seconds is accepted. A future, missing or invalid timestamp does not confirm freshness.
- Do not discard older offers from the first-20 mean merely because they are older than 15 minutes; freshness is established by the newest offer.
- Do not deduct the displayed commission from this route step.
- Reject HTTP 401/403/429, non-200 responses, malformed payloads, wrong direction, non-positive/non-finite rates, empty offers and stale data. Do not retry access-denied or rate-limited responses.
- A failed or stale read is unavailable. Never reuse a previous quote as current.

### Access boundary

The observed frontend endpoint is not proof of an approved server-to-server API. Previous unauthenticated direct requests returned HTTP 401 and later HTTP 429. The current implementation reuses only the request/response already produced by the owner's authenticated page in a manually supervised, one-shot workflow. It does not establish permission for unattended polling.

Do not copy cookies, session tokens, OAuth authorization codes, browser storage or authorization headers into cloud secrets, artifacts, logs, Telegram or repository files. Do not spoof device identity, bypass CAPTCHA/MFA/device binding, or retry around HTTP 429.

## Scheduling and persistence

Do not enable scheduled collection yet. The hourly schedule remains disabled until Money Storage, BlackBit, Winance and both Sberkassa route steps are validated, and the shared collector, freshness gates, atomic update and stale-quote blocking are verified. No Telegram delivery is assumed to be configured.


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


## E-ID frontend integration evidence (2026-11-18)

Further public-page inspection found additional evidence that the e-id.cards frontend library is used by Money Storage:

- The current public https://storage.money/login page displays a "Login with E-ID" action.
- A third-party archived site-technology snapshot of https://storage.money/login lists https://e-id.cards/js/eid.js among the page's loaded JavaScript resources.
- The same library URL is listed in third-party snapshots of sberkassa.site and several unrelated payment/project sites. This supports that eid.js is a shared browser-side integration library, but does not reveal its API contract.
- Direct retrieval of https://e-id.cards/js/eid.js was not available through the public research browser. No source code, endpoint names, token exchange method, or client-secret handling could therefore be verified.
- The accessible E-ID agreement describes the identity provider's relationship with relying-party "Agents" and says user data is shared according to the individual authorization, but it does not publish developer documentation or server API details.

Sources inspected:
- Money Storage login page: https://storage.money/login
- E-ID agreement: https://e-id.cards/agreement/
- Third-party page technology snapshot: https://codomaza.com/analiz/storage.money

### Updated conclusion

The link between Money Storage and e-id.cards is now supported by both the live Money Storage login page's E-ID action and a public page snapshot referencing the E-ID JavaScript library. This confirms a browser-side integration, not a cloud/server-side OAuth contract. The library URL being referenced is not sufficient evidence to infer token endpoints or to build an OAuth client.

The next safe step is to obtain the eid.js source through an ordinary browser's public page loading (without credentials or session export), or obtain the provider's integration specification. If the script is retrieved, inspect only its public client-side behavior for documented redirect construction and callback handling; do not attempt to extract secrets, tokens, cookies, or bypass access controls. Keep production polling disabled until server-side authorization is explicitly supported.


## Additional E-ID relying-party comparison (2026-11-18)

A public technical article describing the `erub.money` login flow independently records an authorization-code redirect to `e-id.cards/oauth/user`, with `response_type=code`, profile scopes `firstname surname email phone`, client ID `rtex`, and an `erub.money` callback. This is evidence that e-id.cards is used by more than one relying party and that client identifiers/callbacks are application-specific. It does not establish that the `rtex` client, callback, or any token-exchange configuration can be reused by Money Storage; the observed Money Storage client remains `moneystorage` with its own callback.

The public E-ID login page and agreement are readable, but the JavaScript resource `https://e-id.cards/js/eid.js` could not be retrieved by the available research browser. A direct retrieval attempt from the working environment also failed before HTTP connection because DNS resolution was unavailable. No source code or API behavior is inferred from that failure.

Sources:
- E-ID login page: https://e-id.cards/login
- E-ID agreement: https://e-id.cards/agreement/
- Public third-party technical article documenting the separate erub.money relying-party flow: https://erub-razbor.com/e-id-cards/

### Decision remains unchanged

Do not reuse the `rtex` client or guess token endpoints. Continue to require a Money Storage / e-id.cards supported integration specification or an officially approved cloud OAuth client and callback before implementing server-side authentication. Production polling remains disabled.


## E-ID public resource and discovery checks (2026-11-18)

Additional searches and direct public-page retrieval attempts were performed:

- Search-indexed technical snapshots of Money Storage and Sberkassa independently list `https://e-id.cards/js/eid.js` as a browser script. A separate public site snapshot also lists the same script. This confirms repeated use of the shared frontend library, but these snapshots expose only the script URL, not its contents.
- The E-ID JavaScript URL could not be opened by the available research browser. Direct attempts to open `https://e-id.cards/.well-known/openid-configuration` and `https://e-id.cards/oauth/.well-known/openid-configuration` were also inaccessible. These are failed retrieval attempts, not evidence that the endpoints do not exist.
- A public technical article documents a separate `erub.money` relying-party redirect through `e-id.cards/oauth/user`, using client ID `rtex`, scopes `firstname surname email phone`, and callback `erub.money/oauth/callback/eid`. The values differ from Money Storage's observed client ID `moneystorage` and callback `storage.money/oauth/callback/eid`; they must not be interchanged.
- The E-ID agreement describes the Service/User/Agent relationship but does not publish an OAuth token endpoint, developer registration procedure, API credentials, or server-side integration rules.

References:
- Money Storage page snapshot listing the E-ID script: https://codomaza.com/analiz/storage.money
- Sberkassa page snapshot listing the E-ID script: https://codomaza.com/analiz/sberkassa.site
- E-ID agreement: https://e-id.cards/agreement/
- Separate erub.money flow description: https://erub-razbor.com/e-id-cards/

### Conclusion after this check

No publicly retrievable E-ID script source, OAuth discovery metadata, token endpoint, or server integration specification was obtained. Do not infer endpoint paths from OAuth conventions and do not reuse the `rtex` client. The remaining blocker is provider-side: Money Storage / e-id.cards must confirm an approved server-side client, token exchange endpoint and authentication method, redirect URI registration, PKCE requirements, token refresh policy, and permitted polling use. Live Money Storage polling remains disabled.


## Server-side public API search (2026-11-18)

The investigation was narrowed to a supported read-only server API that would avoid browser OAuth entirely.

Findings:
- Searches for official `storage.money` API documentation, developer endpoints, and public offer APIs did not return an official API specification or a documented server credential flow.
- The only endpoint currently evidenced by the site's frontend is `GET https://storage.money/public_deals/fetch` with `offset`, `limit`, `from`, and `to`; the site's frontend reads offers from the response `data` field. This is a frontend route, not proof of a supported public API.
- Existing unauthenticated tests of this exact route returned HTTP 401 and, on a later repeat, HTTP 429. Do not repeat requests or attempt alternate headers, user agents, paths, or query variations to evade those responses.
- Search surfaced `docs.exchanger.money`, which documents a separate service on `api.exchanger.money` using HMAC credentials and an offers endpoint. Its hostname, product, and authentication scheme do not match `storage.money`; there is no evidence that it is operated by or integrated with Money Storage. It is explicitly excluded as a false-positive search result.
- The Money Storage public-facing site identifies `info@storage.money` as its contact address, but no public developer/API documentation was found.

References:
- Money Storage public site/contact: https://www.money-storage.id/
- Separate Exchanger.Money API documentation (not Money Storage): https://docs.exchanger.money/

### Decision

No supported unauthenticated/server-side read API for Money Storage has been verified. Keep the existing provider disabled for live polling. Do not replace the source with `api.exchanger.money` or any other similarly named service. The next useful input is explicit confirmation from Money Storage that `public_deals/fetch` is intended for server-side read use, together with its supported authentication (if any), rate limit, and exact currency-filter values; alternatively, they can provide a distinct documented read-only endpoint/API key. The first-20 arithmetic-mean calculation and all other route rules remain unchanged.


## Follow-up read-only API verification (2026-11-18)

The current public `/login` page was opened directly and confirms the visible "Login with E-ID" action and the support contact `info@storage.money`. No API/developer documentation link is exposed in the page text. Exact public searches for `storage.money/public_deals/fetch`, `public_deals` on the official domain, and Money Storage API/developer endpoint documentation returned no indexed official specification.

Direct public retrieval of `https://storage.money/public_deals/fetch` without the required query/auth context was not available through the research browser. This is an access limitation of the research browser and is not a new HTTP status observation; the previously recorded direct tests (401 and later 429) remain the only observed HTTP results. The E-ID JavaScript resource was likewise inaccessible to the research browser.

The repository adapter was reviewed without changes. It currently makes a single HTTPS GET with `offset=0`, `limit=20`, and explicitly configured `from`/`to` filters, rejects non-200 and non-`result=ok` responses, does not retry, and does not reuse stale data. The parser filters the raw `src_currency=ECR`, `dst_currency=USDT` direction, then averages the first 20 matching records. The endpoint's intended server-side support and exact filter semantics remain unconfirmed, so the adapter must stay disabled in production until Money Storage confirms those points.

### Next actionable provider request

Ask Money Storage support to confirm in writing: (1) whether `GET /public_deals/fetch` is approved for automated server-side read-only polling, (2) exact `from=ECR` / `to=USDT` values for the "Всем предлагают" tab, (3) whether an API key or other machine credential is required, (4) allowed request frequency and rate-limit behavior, and (5) whether the first page is stable and sorted in the same order as the UI. Do not send account passwords, browser cookies, session tokens, or OAuth authorization codes in that request.


## Expanded public documentation search (2026-11-18)

A broader exact-domain search was run for Money Storage API documentation, developer access, the `public_deals/fetch` route, and read-only offer endpoints.

Findings:
- The indexed Money Storage site `https://www.money-storage.id/` confirms the E-ID login option and lists `info@storage.money` as its support contact. The site text exposes no developer/API documentation link.
- The indexed `https://storage.money/privacy` page lists the same support email but no API integration specification.
- Third-party how-to pages describe browsing Deals / Everyone Offers in the authenticated Money Storage interface and state that rates are updated in real time. These are user guides, not evidence of a supported public API or machine-access permission.
- Search results for `money-storage.info` are a separate hostname and were not treated as authoritative documentation for `storage.money`.
- No official docs for a read-only server API, API key issuance, request signing, or server-side polling were found. A direct browser open of the indexed `money-storage.id` site failed with a 502 from the research browser; this does not establish an outage or a response from the actual `storage.money` API.

References:
- Money Storage indexed login page: https://www.money-storage.id/
- Money Storage privacy page: https://storage.money/privacy
- Third-party Deals usage guide (non-authoritative): https://myflow.fans/ru/guide/money-storage

### Research outcome

No additional endpoint or supported server-side read method was identified. Do not infer API access from the UI's real-time rate display or from third-party user guides. The exact known frontend route remains `GET /public_deals/fetch`, but its use for unattended server polling is unconfirmed and unauthenticated calls have previously returned 401/429. Keep production polling disabled. Further progress now requires an explicit support response or an official developer specification; repeating public searches or probing the endpoint is unlikely to produce new reliable evidence.


## Website frontend and authenticated-deals investigation (2026-11-18)

A follow-up static/public-page report, `money-storage-web-analysis.md`, was reviewed. It deliberately distinguishes observed facts from unverified plans.

### Confirmed public-page observations

- `https://storage.money/` redirects to `https://storage.money/login`.
- The public login page displays a **Login with E-ID** action.
- The page links to the Android APK at `https://storage.money/resources/app-money-storage.apk`. This identifies the site's linked APK download location, but the previously analyzed local APK's authenticity is confirmed only after downloading that exact file and comparing its SHA-256 with the analyzed file.
- The page lists `info@storage.money` as its contact address and links to `/privacy` and `/aml`.

### What remains unverified

The earlier static investigation did not access the authenticated Deals page. Its conclusions about the absence of an authenticated Fetch/XHR trace were superseded by the later browser capture documented below. At that earlier stage it did not establish:

- the actual request used to retrieve offers;
- request method, URL, query parameters, or required headers;
- whether the first 20 records are selected server-side or in the browser;
- response schema, pagination, ordering, or the exact meaning/units of `rate`;
- whether the displayed USDT → ECR direction maps to the parser's current raw currency fields;
- E-ID session lifetime, refresh behavior, MFA/CAPTCHA requirements, or device/IP binding;
- whether persistent cloud-browser automation is permitted by the service.

Framework, bundler, and HTTP library are also unknown because the source HTML and JavaScript bundles were not available to the report author. Third-party technology-scan claims are not treated as confirmed implementation evidence.

### Architecture decision

Keep the production Money Storage poller **disabled**. Do not change `money_storage.py`, its currency filters, or the first-20 arithmetic-mean business rule based on this report.

The next evidence-gathering step is one of:

1. Obtain written confirmation from Money Storage support of an approved read-only server API, its authentication, exact currency filters, ordering, and rate limits; or
2. Have the account owner manually inspect the authenticated Deals page in a normal browser and provide only a manually redacted request/response structure.

Do not send HAR files, cookies, Authorization values, session IDs, CSRF tokens, OAuth codes, account identifiers, or personal data. A redacted trace should retain only request method, path, query parameter names (and only non-personal values where safe), header names, status, content type, and JSON field names/types. Review the redacted output manually before sharing it.

A cloud Playwright persistent profile remains a **candidate, not an approved implementation**. It may be evaluated only if the owner can complete the normal E-ID login in that cloud browser and the service permits this read-only automation. Any CAPTCHA, MFA, or device-binding challenge must remain a manual owner action; no bypass or session transfer from Android is allowed.

### Current conclusion

The web report adds no verified deals endpoint or authenticated response schema. The previously observed frontend route `GET /public_deals/fetch` remains an unverified frontend route, not a supported public server API. Prior 401/429 observations remain unchanged; do not repeat probes or work around rate limits. No code or business logic was changed as a result of this investigation.


## Authenticated browser Network capture (2026-11-18)

The account owner had already authenticated in Chrome on the Samsung device and opened the Money Storage Deals page. With Chrome brought to the foreground, the Chrome DevTools Protocol became responsive and a read-only Network capture was completed. The capture records request metadata and a locally summarized JSON response shape; it does not export cookies, authorization values, session identifiers, CSRF tokens, or raw offer records.

### Confirmed request

The Deals page issued this request from its own frontend:

```http
GET https://storage.money/public_deals/fetch?offset=0&limit=20&from=ECR&to=USDT
```

Observed response metadata:

- HTTP status: `200`
- Content type: `application/json`
- Envelope: `result` is the string `"ok"`
- `data`: array containing exactly 20 records in this capture
- Every record exposed the following fields and types:
  - `rate`, `back_rate`, `create_time`, `request_id`: number
  - `commission`, `commission_currency`, `dst_amount`, `dst_currency`, `src_amount`, `src_currency`: string

The captured rows all had raw `src_currency=ECR` and `dst_currency=USDT`; all 20 `rate` values were positive numbers. The browser-side summary of this one observation produced an arithmetic mean of approximately `0.1999514815`. This is a transient observation, not a persisted quote or proof of guaranteed execution.

### Verified UI direction mapping

The page's selected filters were `select_from=ECR` and `select_to=USDT`. The visible public-offer cards rendered the accepting user's direction as **Give USDT / Receive ECR**. The loaded frontend script maps public (non-own) offer fields by displaying raw `dst_amount/dst_currency` as the amount given by the accepting user, and raw `src_amount/src_currency` as the amount received. Thus the raw API pair `src=ECR,dst=USDT` corresponds to the displayed **USDT -> ECR** direction used by the existing parser.

The current page's tab labels were observed as `Я предлагаю` and `Всем предлагают`; the captured request was made on the latter view. The project explicitly selects **«Всем предлагают»**. Do not substitute `Я предлагаю` or the similarly worded «Мне предлагают» view.

### Frontend behavior evidence

The loaded `/js/system.js` script contains the frontend function that reads the selected `select_from` and `select_to` values, builds `offset`, `limit`, `from`, and `to` query parameters, and calls `/public_deals/fetch`. The same script's public-offer renderer reverses raw src/dst for the accepting user's displayed give/receive direction.

### What this does and does not prove

This is the first verified authenticated browser request and response schema for the live Deals view. It resolves the request path, query values, response envelope, field names/types, 20-row page size, and raw-to-displayed currency-direction mapping for this view.

It does **not** prove that the route is officially supported for unattended server-side polling, that an unauthenticated cloud request will succeed, or that Money Storage permits automated polling outside its normal browser UI. Earlier direct unauthenticated requests returned 401 and later 429; those observations remain valid and must not be retried or bypassed. The authenticated browser's session was not exported or transferred.

### Implementation decision

- Keep the existing parser's raw pair mapping `src=ECR,dst=USDT` -> displayed `USDT -> ECR`.
- The provider's filter configuration for this exact frontend view is `from=ECR`, `to=USDT`.
- Keep the first-page limit at 20 and the arithmetic mean of the first 20 matching `rate` values; do not sum amounts or select a best offer.
- Keep the seller-paid commission as informational metadata, not a deduction from this route step.
- Do not enable cloud polling or change authentication behavior until Money Storage confirms that this frontend endpoint may be used by an automated cloud reader and specifies any required supported access method and rate limits.


## Follow-up implementation guard (2026-11-18)

The authenticated standalone-Chromium run has now read the `Всем предлагают` tab in the same manually authenticated session and published a normalized artifact containing 20 offers. Its arithmetic mean was independently checked against the 20 row rates. This confirms the selected UI source and current response shape for this capture.

The selected tab and first-20 row set are now confirmed for a one-shot manually authenticated cloud-browser read. Do not enable unattended scheduled server-side polling until Money Storage confirms that access method, request frequency, and rate limits are permitted. The `.env.example` filter values describe the captured frontend request only; they are not authorization or proof of production cloud access.
