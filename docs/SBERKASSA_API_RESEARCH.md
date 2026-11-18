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
