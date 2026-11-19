# Quote and offer storage policy

Status: approved requirement. The current prototypes must be updated to enforce it before any production polling is enabled.

## Storage rules

| Source | Stored data | Lifetime |
|---|---|---|
| BlackBit | One current normalized ECR/USDT quote | Until the next polling request replaces it |
| Winance | One current normalized ERUB/USDT quote | Until the next polling request replaces it |
| Money Storage | Current eligible offers needed for calculation | Until the next successful refresh replaces them |
| Sberkassa | Current rates/offers needed for calculation | Until the next successful refresh replaces them |

No source has a historical quote/offer archive. Do not append snapshots to an observations table.

## Replacement and failures

- Store at most one current snapshot per source (or per source + market key if a source later returns multiple independently needed offers).
- On a successful refresh, atomically replace the previous snapshot with the newly validated data.
- On a failed, empty, malformed, or invalid refresh, do not overwrite a valid snapshot with bad data. Mark the source unavailable/stale; the previous value may remain for diagnostics but must not be treated as current or used in the full route.
- Keep operational source-health metadata separately. It is not quote history and must not contain credentials or raw provider payloads.
- Do not keep prior snapshots, audit copies, or historical rows.

## Polling cadence

BlackBit and Winance polling is to be configurable within **900 to 3600 seconds (15 minutes to 1 hour)**. The exact interval is intentionally undecided and will be selected later. Do not treat 300 seconds as an approved production cadence. Money Storage and Sberkassa refresh cadence will be set when their cloud adapters and access methods are established.

## Current implementation gap

The current prototype schemas and handlers still append BlackBit/Winance observations. They do not yet implement the current-only replacement rule. Money Storage and Sberkassa adapters are not implemented. This policy is a requirement, not a claim that enforcement is already active. Do not enable production polling until the schemas, handlers, failure behavior, and tests enforce current-only storage.
