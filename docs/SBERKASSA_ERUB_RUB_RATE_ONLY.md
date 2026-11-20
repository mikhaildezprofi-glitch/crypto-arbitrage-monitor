# Sberkassa ERUB -> RUB: rate-only calculation

## Scope

- Source page: `https://sberkassa.site/deals#tab-3`.
- Tab: **«Всем предлагают»**.
- Direction: **ERUB -> RUB**.
- Only the exchange rate is relevant. Ignore commissions, amounts, volumes, reserves, limits, and liquidity.
- Use the first 20 matching offers in the page/API order, or all if fewer than 20; calculate an unweighted arithmetic mean.
- Mark the result indicative, not guaranteed executable.

## Important schema finding

The authenticated inspection of `/public_deals/fetch` returned 27 `rate` and 27 `back_rate` values. They are reciprocal in the sampled records (for example, `rate=0.03849115` and `back_rate=25.98`). The same response contained both small and large `rate` values, so a blind average of every `rate` field would mix directions or misinterpret the displayed direction.

The sanitized inspection did not retain the offer currency/direction fields or request parameter values needed to filter the exact ERUB -> RUB records. Therefore the correct field (`rate` versus `back_rate`) is not yet proven. The calculation helper requires the caller to provide an already direction-filtered offer list and an explicit rate field; it deliberately does not guess.

## Freshness

The page-level update marker was not found (`page_updated_at=null`). Offer `create_time` values are not a substitute for the page's last-refresh time. The live quote remains unavailable until a page-level freshness marker or another explicitly approved freshness signal is verified.

## Safety

Read-only inspection and arithmetic only. No deal submission, fund movement, credential export, or CAPTCHA/MFA/device-binding bypass.