# Sberkassa cloud quote-source investigation

Research baseline: 2026-11-18

## Required route steps

These are two separate markets and must have independently verified quote sources:

1. Sberkassa deals: ERUB -> RUB
   UI page: https://sberkassa.site/deals#tab-3
2. Sberkassa exchange: RUB -> USDT
   UI page: https://sberkassa.site/exchange
   Required value only: current displayed rate in the form 1 RUB = X USDT.

The exchange page is not an order-book research task. For RUB -> USDT, the calculator needs only the current displayed conversion rate and its observation time.

## Confirmed public observations

- Opening https://sberkassa.site redirects to /login.
- The public login page displays an E-ID login action.
- Public page research exposed frontend resource names including /js/app.js, /js/auth.js, and /translations/ru.
- A prior Android-side public HTML retrieval succeeded for the login page, but it did not expose quote endpoints.
- Attempts to retrieve some JavaScript resources through the research browser failed because of content-type or retrieval limitations. These failures do not prove that the resources or endpoints do not exist.
- No authenticated quote response has been captured for either required direction.

## Unconfirmed information

For ERUB -> RUB, no verified quote endpoint, HTTP method, response schema, rate, fee, min/max volume, available volume, or freshness semantics are known.

For RUB -> USDT, no verified current rate source, endpoint, response schema, fee, or freshness semantics are known. A previously seen screenshot value is historical only and must never be treated as a current quote.

Do not infer API paths from frontend filenames. Do not use Winance ERUB/USDT as a substitute. Do not use erub.site endpoints: it is a different hostname and service.

## Cloud implementation decision

- No Sberkassa provider adapter is enabled.
- Both Sberkassa route steps are explicitly unavailable until their own read-only data sources are verified.
- The collector must not synthesize, estimate, or reuse either rate.
- Unknown fees remain unknown; they must not be assumed to be zero.
- The five-step calculator must refuse to publish a full-route result if either Sberkassa quote or its required fee data is missing.
- No provider-support request will be sent. Continue cloud-side research using public technical material and the existing repository evidence only.

## Security boundaries

- Do not guess or probe undocumented authenticated endpoints.
- Do not export or transfer browser cookies, session tokens, authorization headers, CSRF values, or personal account data.
- Do not bypass CAPTCHA, MFA, device binding, or other access controls.
- Do not create, accept, edit, or cancel deals; do not pay, transfer, deposit, or withdraw.
- Only GET/read-only access is in scope.

## Evidence required before enabling either adapter

A future implementation must have, independently for each direction:
1. Exact quote source and host.
2. Request method and path.
3. Sanitized parameter names and safe non-personal values.
4. HTTP status and content type.
5. Response envelope and field names/types.
6. Verified rate direction and meaning.
7. Required fee semantics.
8. Quote observation/freshness behavior.
9. A permitted cloud-side access method.

Until then both provider keys remain unavailable and the full route remains blocked.
