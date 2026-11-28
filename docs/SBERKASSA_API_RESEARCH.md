# Sberkassa quote-source investigation

Research date: 2026-11-18

## Scope

The route requires two distinct read-only quote steps:

1. Sberkassa: ERUB -> RUB
2. Sberkassa Exchange: RUB -> USDT

Do not assume these are the same market, endpoint, fee schedule, or direction. No order placement, payment, deposit, withdrawal, or account mutation is part of this project.

## Confirmed public-page observations

- Opening https://sberkassa.site redirects to https://sberkassa.site/login.
- The current public login page displays an E-ID login action.
- The page is a login/marketing page; it does not expose a public quote table or API documentation in the retrieved page text.
- A third-party site-technology snapshot dated 2025-04-07 lists these frontend resources for the Sberkassa login page:
  - `/js/alert.js?v=0.226`
  - `/js/auth.js`
  - `/js/lib/clipboard.min.js`
  - `/js/lib/jquery-ui.min.js`
  - `/js/lib/jquery.min.js`
  - `/js/lib/selectBoxIt.min.js`
  - `/js/lib/sortable.js`
  - `/translations/ru`
  - `https://e-id.cards/js/eid.js`
- The public research browser could not retrieve the JavaScript resources as text: it rejected the JavaScript content type or reported the URL inaccessible. This is a tooling limitation, not proof that the resources are unavailable to a normal browser.
- The earlier attempt to retrieve `/site/currency_pairs` through the research browser returned an internal retrieval error. This does not establish that the route is absent or that the live service is down.

## Exclusions and false positives

- `erub.site` is a different hostname and must not be substituted for `sberkassa.site`.
- Public routes documented for `erub.site` (such as `/site/rates` and `/site/merchant_config`) are not evidence of Sberkassa quote endpoints.
- Winance ERUB/USDT is a separate route step and does not provide the Sberkassa ERUB/RUB or Sberkassa Exchange RUB/USDT quote.
- No endpoint names, response schemas, rates, commissions, limits, or volumes are inferred from frontend filenames.

## Shared E-ID authentication workflow

Sberkassa uses the same E-ID identity provider as Money Storage, but its login workflow must begin on Sberkassa's own page. The cloud inspection workflow opens `https://sberkassa.site/login` directly in a standalone Chromium profile:

1. Open `https://sberkassa.site/login`.
2. Complete the E-ID redirect initiated by Sberkassa manually in the same browser tab.
3. The probe confirms that the browser visited `e-id.cards` and then returned to `sberkassa.site/login`.
4. Continue inspecting the authenticated Sberkassa pages in that same session.

Do not open `storage.money/account` as an intermediate login step in the Sberkassa workflow. Money Storage has its own separate workflow target. Any additional Sberkassa consent or login is completed manually. No cookies or tokens are copied.

1. Open `https://storage.money/account` to establish the normal E-ID authorization flow.
2. The account owner completes E-ID and any ordinary verification manually in the visible noVNC browser.
3. Wait for the normal return to `https://storage.money/account`.
4. Navigate to `https://sberkassa.site/login` in that same Chromium profile. The browser may reuse the E-ID identity-provider session; if Sberkassa asks for additional consent or authentication, the account owner handles it manually.

This reuses the proven browser infrastructure and avoids a second authentication implementation. It does not assume that a Money Storage application session itself grants access to Sberkassa. No cookies, tokens, authorization headers, or CSRF values are exported or transferred. The browser performs navigation only; it does not submit login forms or bypass verification.

## Current implementation decision

No Sberkassa or Sberkassa Exchange provider adapter is implemented. Both route steps remain unavailable until their own read-only quote sources are verified.

Do not guess undocumented endpoint paths or replay authenticated requests. Do not export or transfer browser cookies, session tokens, authorization headers, CSRF values, or personal account data. Any authenticated inspection must be explicitly authorized by the account owner and limited to redacted request metadata and response schema. Do not bypass CAPTCHA, MFA, or device binding.

## Next evidence required

For each of the two route steps, obtain:

1. The exact UI page/section that displays the relevant direction.
2. The normal browser request method and path used to load that quote.
3. Redacted query parameter names and non-sensitive filter values.
4. HTTP status, content type, response envelope, and JSON field names/types.
5. The precise rate meaning and direction.
6. Applicable commission, min/max limits, available volume, and quote timestamp/freshness semantics.
7. Confirmation that read-only automated cloud polling is permitted, plus supported authentication and rate limits if authentication is required.

Until those facts are established independently for both steps, the full route must remain unavailable. Unknown fees or limits must not be treated as zero or unlimited.

## Sources inspected

- Current public login page: https://sberkassa.site/login
- Third-party frontend-resource snapshot (dated 2025-04-07): https://codomaza.com/analiz/sberkassa.site

The third-party snapshot is used only to identify historical frontend resource paths. It is not treated as authoritative API documentation.


## Follow-up public resource checks (2026-11-18)

Additional exact-host searches for Sberkassa rate endpoints and API routes returned no official API documentation or indexed response schema.

Direct retrieval attempts:
- `https://sberkassa.site/js/auth.js` was rejected by the research browser because the response content type is JavaScript.
- `https://sberkassa.site/js/alert.js?v=0.226` was inaccessible through the research browser.
- `https://sberkassa.site/site/currency_pairs` was also inaccessible through the research browser.
These are retrieval limitations only; they do not prove that the resources or route do not exist.

Search results also surfaced technical material for the separate hostname `erub.site`, including `/site/rates` and `/site/merchant_config`. These endpoints belong to `erub.site`, not `sberkassa.site`, and are explicitly excluded from this provider investigation. Likewise, Winance pair IDs and endpoints cannot substitute for either Sberkassa step.

### Current result

No verified Sberkassa endpoint, quote schema, commission, limit, or volume has been obtained. The two Sberkassa route steps remain unavailable. The next useful evidence must come from the normal authenticated Sberkassa UI Network panel, captured with the account owner's authorization and sanitized to remove all credentials and personal data, or from official provider documentation.

## Public frontend inspection from Android (2026-11-18)

A read-only request from the user's Android environment successfully retrieved `https://sberkassa.site/login` (HTTP success; HTML content type; 9,083 bytes). The HTML referenced these same-origin scripts:

- `/translations/ru`
- `/js/lib/jquery.min.js`
- `/js/lib/jquery-ui.min.js`
- `/js/lib/clipboard.min.js`
- `/js/lib/sortable.js`
- `/js/lib/selectBoxIt.min.js`
- `/js/app.js`
- `/js/alert.js`
- `/js/auth.js`

The public translation resource contains UI labels such as "Public deals proposed by you", "Who can accept this deal", "Who offer the deal", "Create deal", and "Confirmation to exchange". These strings show that the site frontend includes deal/exchange concepts, but they do not identify a quote endpoint or establish the rate semantics for either required route direction.

The direct public fetch of `/js/app.js` failed with an HTTP error. No response body or API schema was obtained from it. No credentials, cookies, tokens, account data, or authenticated response bodies were requested or collected.

An attempted Chrome DevTools Protocol connection through the existing local forwarding port returned `RemoteDisconnected`; no authenticated network events were captured. This is a connection/forwarding failure, not evidence that Sberkassa has no API.

### Updated current result

The public frontend structure is now partially confirmed, but no Sberkassa quote endpoint, quote schema, rate, commission, limit, volume, or freshness rule is confirmed. Both Sberkassa route steps remain unavailable. Next evidence must come from a successful, authorized, sanitized Network capture in the exact authenticated UI pages for ERUB -> RUB and RUB -> USDT, or official provider documentation.


## Project-selected page and freshness rule (2026-11-20)

The account owner has confirmed the intended Sberkassa source and quote-freshness semantics:

- For the ERUB -> RUB route step, use only `https://sberkassa.site/deals#tab-3`, the **«Всем предлагают»** tab.
- Do not substitute «Мне предлагают» or «Я предлагаю».
- Ignore each offer's individual creation timestamp when deciding whether the current quote snapshot is fresh. Offers may have different creation times.
- For freshness, use the UTC timestamp when the browser successfully finishes loading the selected page. Do not search for an internal quote-update timestamp or a separate quote-refresh event.
- Record that page-load time as the quote's observation time. A page that fails to load, is not the intended page, or does not expose the required rate/direction is unavailable. Do not reuse an older snapshot as fresh.

Each Sberkassa route step has its own page-load timestamp. For **Sberkassa Exchange RUB -> USDT**, open `https://sberkassa.site/exchange` directly and use the Chromium `Page.loadEventFired` time for that navigation as `observed_at_utc`. The browser page-load timestamp is the selected freshness anchor; the exchange's internal quote-update time is not required.

This is a project source-selection and acceptance rule, not evidence that the live Sberkassa page or its network request has already been captured. The exact request, response schema, current rate, page timestamp, and permitted polling method remain unverified. Do not implement or enable either provider until those facts are captured in the normal authenticated browser session or confirmed by official documentation. Do not bypass CAPTCHA, MFA, or device binding, and do not export cookies or session tokens.


## Project-selected rate calculation rule (2026-11-20)

The account owner has confirmed that Sberkassa commissions and liquidity/volume data are not needed, following the Money Storage approach:

- For each required direction where the page exposes multiple independent offers, take the first 20 matching offers in the page/API order and calculate the unweighted arithmetic mean of their positive finite rate values.
- If fewer than 20 matching offers are available, average all valid available offers. If there are no matching offers, or a required rate is malformed, non-finite, zero, or negative, mark that quote unavailable.
- Do not read, require, calculate with, or apply commissions, offer amounts, volumes, reserves, minimums, maximums, or liquidity. Do not sum amounts, select a single offer, or model partial fills.
- For `/exchange`, first determine whether the UI actually presents a list of independent offers. If so, apply the same first-20 arithmetic mean. If it presents only one published conversion rate, use that single rate; do not fabricate a 20-offer average.
- The average is indicative only and is not an execution guarantee.
- Keep page freshness independent for each route step: ERUB -> RUB uses the `/deals#tab-3` page marker; RUB -> USDT uses the `/exchange` page marker. Individual offer creation times are ignored for freshness.

The browser probe is intentionally limited to rate/price and timestamp-related response fields. Commission, volume, reserve, and limit fields are outside the required capture.


## Updated RUB -> USDT observation-time rule (2026-11-26)

The account owner has explicitly selected successful browser page-load time as the freshness anchor for Sberkassa Exchange RUB -> USDT. The cloud probe records the UTC time at which Chromium emits `Page.loadEventFired` for the direct `/exchange` navigation. That timestamp is stored as `page_loaded_at_utc` and `observed_at_utc` in the inspection artifact and is used instead of an exchange-internal quote-update timestamp. No internal quote-update time or separate quote-refresh event is required. The Money Storage server-side `create_time` rule remains unchanged.
