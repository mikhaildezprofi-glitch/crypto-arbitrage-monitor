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
- Freshness must be established by the page's own visible update/refresh timestamp, and only when that timestamp corresponds to a successful refresh of the displayed offers. Merely opening the tab or seeing a newly rendered page is not proof that the underlying offers were refreshed.
- Record the page's confirmed update time as the quote's observation time. If the page does not show a trustworthy update time, or the refresh fails, mark this source unavailable; never reuse an older snapshot as fresh.

The separate ERUB -> RUB page timestamp must not be applied to the second route step. For **Sberkassa Exchange RUB -> USDT**, inspect `https://sberkassa.site/exchange` independently and use that page's own confirmed update time. Its quote semantics, fees, limits, and refresh behavior still require verification.

This is a project source-selection and acceptance rule, not evidence that the live Sberkassa page or its network request has already been captured. The exact request, response schema, current rate, page timestamp, and permitted polling method remain unverified. Do not implement or enable either provider until those facts are captured in the normal authenticated browser session or confirmed by official documentation. Do not bypass CAPTCHA, MFA, or device binding, and do not export cookies or session tokens.
