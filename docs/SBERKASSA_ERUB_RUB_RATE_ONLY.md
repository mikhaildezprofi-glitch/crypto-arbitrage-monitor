# Sberkassa ERUB -> RUB: rate-only capture

Updated: 2026-11-20

## Confirmed source selection

- Source: `https://sberkassa.site/deals#tab-3`.
- Tab: **«Всем предлагают»**.
- Direction: **ERUB -> RUB**.
- Endpoint observed in the authenticated page: `GET /public_deals/fetch`.
- Latest inspected response: HTTP 200.
- The response exposed 27 `rate` fields and 27 `back_rate` fields.

## Calculation

- Use only each offer's `rate` field in the response order.
- Take the first 20 offers; if fewer than 20 exist, use all available offers.
- Calculate the unweighted arithmetic mean.
- Ignore `back_rate`, offer creation timestamps, commissions, amounts, volumes, reserves, limits, and liquidity.
- Mark the result as indicative, not an execution guarantee.
- Empty offers or invalid, non-finite, zero, or negative selected rates make the quote unavailable.

## Freshness remains a separate gate

The inspection did not find a visible page update marker (`page_updated_at` was null). Individual offer `create_time` values are not a substitute. Until a trustworthy page-level refresh timestamp is identified and correlated with a successful refresh, the quote must remain unavailable for the live route calculation.

## Scope boundary

This capture task covers only the Sberkassa ERUB -> RUB offer quote. The `/exchange` page is not part of this quote source and is not needed to calculate this individual step. Any separate RUB -> USDT route step must be handled independently and must not be conflated with ERUB -> RUB.

## Safety

Inspection is read-only. Do not submit deals, move funds, export cookies/tokens, or bypass CAPTCHA, MFA, or device binding.