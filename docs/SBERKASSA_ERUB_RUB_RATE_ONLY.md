# Sberkassa ERUB -> RUB: rate-only calculation

## Scope

- Source page: `https://sberkassa.site/deals#tab-3`.
- Tab: **«Всем предлагают»**.
- Direction: **ERUB -> RUB**.
- Use only the `back_rate` field. Ignore `rate` completely.
- Only the exchange rate is relevant. Ignore commissions, amounts, volumes, reserves, limits, and liquidity.
- Use the first 20 matching offers in the page/API order, or all if fewer than 20; calculate an unweighted arithmetic mean.
- Mark the result indicative, not guaranteed executable.

## Rate field

The implementation now takes `back_rate` exclusively for ERUB -> RUB. The reciprocal `rate` field is ignored, even when present. The caller must still filter the source records to the ERUB -> RUB direction before calculation; the arithmetic helper does not infer direction from amounts or reciprocal values.

## Freshness

The previous authenticated inspection found no page-level update marker (`page_updated_at=null`). Offer `create_time` values are not a substitute for the page's last-refresh time. The live quote remains unavailable until a page-level freshness marker or another explicitly approved freshness signal is verified.

## Safety

Read-only inspection and arithmetic only. No deal submission, fund movement, credential export, or CAPTCHA/MFA/device-binding bypass.
