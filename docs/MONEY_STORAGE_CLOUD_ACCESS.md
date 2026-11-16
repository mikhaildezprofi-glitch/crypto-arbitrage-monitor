# Money Storage cloud access decision

## Status

Live cloud polling is **blocked** until Money Storage provides a supported server-side read-access method.

The repository currently contains a pure parser and quote builder. They do not make HTTP requests and do not authenticate. The frontend JavaScript exposes the public-deals route:

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

Do not enable a scheduled job while the endpoint cannot be accessed through an approved server-side method. A cron job that repeatedly receives 401/429 is not live quote monitoring.

Once access is approved, implement a cloud polling worker at 900-second intervals, persist the latest quote and observation timestamp, expose explicit source health/error state, and feed only fresh quotes into the route collector. Keep credentials in the cloud provider's secret store and out of repository files, Telegram messages, and logs.

## Acceptance checks

- A cloud-run integration test can retrieve the first page using the officially supported access method.
- Unit tests cover the first-20 arithmetic mean, fewer-than-20 behavior, empty results, wrong pair, malformed payload, HTTP/auth errors, and timestamping.
- An unsuccessful poll leaves the source unavailable; it does not publish a stale quote as fresh.
- The full route remains unavailable whenever this required source is unavailable or stale.
