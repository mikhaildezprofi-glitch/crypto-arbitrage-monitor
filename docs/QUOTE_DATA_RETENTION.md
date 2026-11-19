# Quote and offer storage policy

Status: approved requirement. The Python and JavaScript prototype schemas and handlers store only one current BlackBit/Winance snapshot per source using UPSERT. CI passed for the current prototype changes; Money Storage and Sberkassa adapters remain unimplemented.

## Storage rules

| Source | Stored data | Lifetime |
|---|---|---|
| BlackBit | One current normalized ECR/USDT quote | Until the next polling request replaces it |
| Winance | One current normalized ERUB/USDT quote | Until the next polling request replaces it |
| Money Storage | Current eligible offers needed for calculation | Until the next successful refresh replaces them |
| Sberkassa deals | Current eligible rates/offers needed for the ERUB → RUB stage | Until the next successful refresh replaces them |
| Sberkassa `/exchange` | One current displayed RUB → USDT exchange rate used for the RUB → USDT stage | Until the next successful refresh replaces it |

No source has a historical quote/offer archive. Do not append snapshots to an observations table.

## Replacement and failures

- Store at most one current snapshot per source/market key. The Sberkassa `/exchange` RUB → USDT rate is a separate current value from Sberkassa deal offers; do not store the full page or a rate history.
- On a successful refresh, atomically replace the previous snapshot with the newly validated data.
- On a failed, empty, malformed, or invalid refresh, do not overwrite a valid snapshot with bad data. Mark the source unavailable/stale; the previous value may remain for diagnostics but must not be treated as current or used in the full route.
- Keep operational source-health metadata separately. It is not quote history and must not contain credentials or raw provider payloads.
- Do not keep prior snapshots, audit copies, or historical rows.

## Polling cadence

BlackBit and Winance polling is to be configurable within **900 to 3600 seconds (15 minutes to 1 hour)**. The exact interval is intentionally undecided and will be selected later. Do not treat 300 seconds as an approved production cadence. Money Storage and Sberkassa refresh cadence will be set when their cloud adapters and access methods are established.

## Current implementation gap

The prototype schemas now define `current_quotes` with `source` as the primary key, and successful BlackBit/Winance polls use UPSERT rather than appending history. A failed poll leaves the last snapshot in place but marks the source unavailable, so it cannot be treated as current. CI has passed for the existing Python and JavaScript prototype schema/handler behavior. Money Storage and Sberkassa adapters are not implemented. When added, Sberkassa `/exchange` must persist only the validated displayed RUB → USDT rate as its current snapshot, replacing it on the next successful refresh. Do not enable production polling until CI and failure-path tests pass.
