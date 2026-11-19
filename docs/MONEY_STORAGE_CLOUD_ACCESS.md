# Money Storage cloud access decision

## Current status

Live cloud polling is BLOCKED. Development continues without contacting provider support and without the phone, ADB, Termux, Polydev, or a local browser.

The repository contains a parser, quote builder, and plain HTTPS read-only adapter. The adapter is not enabled for production polling because the observed frontend endpoint has not been established as an approved unattended cloud API.

## Confirmed observations

An authenticated browser Network capture on 2026-11-18 observed the page "Всем предлагают" issuing:

    GET https://storage.money/public_deals/fetch?offset=0&limit=20&from=ECR&to=USDT

The captured response was HTTP 200, JSON, with result="ok" and a data array of 20 records. Observed fields:

- Numeric: rate, back_rate, create_time, request_id.
- String: commission, commission_currency, dst_amount, dst_currency, src_amount, src_currency.

The captured rows used raw src_currency=ECR and dst_currency=USDT. The frontend rendered the accepting user's direction as Give USDT / Receive ECR. This maps to the project's required USDT -> ECR route step.

Unauthenticated direct requests previously returned HTTP 401 and, on a later attempt, HTTP 429. Do not retry or work around those responses.

## Calculation rules

- Use only "Всем предлагают". The "Мне предлагают" view is out of scope.
- Observed request parameters: offset=0, limit=20, from=ECR, to=USDT.
- Parse only raw src=ECR,dst=USDT rows and normalize them to displayed USDT -> ECR.
- Calculate the arithmetic mean of the first 20 available matching rate values, or fewer if fewer are returned.
- An empty or malformed result makes this source unavailable.
- Ignore the displayed commission completely. Do not deduct it from the route.
- Timestamp the quote at successful observation time, not at offer creation time.
- Do not sum offer amounts, select a best offer, infer partial fills, or imply execution.
- Never reuse an old quote after a failed poll.

## Cloud access boundary

The observed URL is a frontend request, not proof of a supported server-to-server API. The browser capture proves the request shape and response schema for one authenticated UI observation; it does not prove that unattended cloud polling is permitted or that the request works without the browser's authorized session.

The observed E-ID redirect uses e-id.cards and the Money Storage relying-party client moneystorage. The token endpoint, client authentication, refresh behavior, PKCE requirements, callback registration, and server-side use are not established. Documentation for the separate e.id service must not be applied to e-id.cards.

Therefore:
- Do not guess OAuth endpoints or exchange authorization codes.
- Do not transfer cookies, browser storage, tokens, or sessions from the phone.
- Do not emulate device identity or bypass CAPTCHA, MFA, or device binding.
- Do not retry HTTP 401, 403, or 429 with alternate headers, paths, or user agents.
- Do not enable production polling until a permitted cloud-side read method is independently established.
- No provider-support request will be sent. Work continues using available public technical evidence and the existing verified parser behavior.

## Cloud implementation behavior

The Money Storage adapter remains opt-in and disabled by default. When disabled, the collector must report money_storage as unavailable and the five-step route must not calculate.

When a permitted read method is established, retain the existing first-20 parser and 900-second target interval. Respect provider rate limits and Retry-After. A failed poll must mark the source unavailable, never freshen or reuse a stale quote.

## Acceptance checks

- Correct tab and raw/displayed direction mapping.
- First-20 arithmetic mean, fewer-than-20 behavior, empty results, wrong pair, malformed payload, and non-finite/non-positive rates.
- Commission is retained only as metadata and excluded from route calculation.
- HTTP 401/403/429 fail closed without retry.
- Failed polls do not publish stale data as fresh.
- Production polling remains disabled unless the cloud access method is permitted and independently verified.
