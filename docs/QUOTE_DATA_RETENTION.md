# Quote data retention policy

Status: approved design requirement for the monitor; enforcement is not implemented in the current prototypes.

## Retention rules

| Source | Data to keep | Retention |
|---|---|---|
| BlackBit | Successful normalized quote observations | 30 days rolling |
| Winance | Successful normalized quote observations | 30 days rolling |
| Money Storage | Latest currently valid offer only | Until the next successful offer refresh replaces it |
| Sberkassa | Latest currently valid offer/rate only | Until the next successful refresh replaces it |

## Required behavior

- BlackBit and Winance history is retained for the most recent 30 days. Older observations must be deleted automatically. The retention window is measured from the observation timestamp in UTC.
- Money Storage and Sberkassa offers must never be appended to the historical observations table. Keep only the current snapshot needed for calculation; replace it atomically after a successful refresh.
- When a refresh fails, do not replace a valid current snapshot with an empty or malformed result. Mark the source unavailable/stale and block the full route according to the existing fail-closed rules. The previous snapshot may remain stored as the last known value, but it must not be treated as current or fresh.
- A successful refresh replaces the previous Money Storage/Sberkassa snapshot. No historical copy, audit trail, or previous-offer archive is retained.
- Source health metadata (last attempt, last success, error class) is operational state, not quote/offer history. It may be retained separately and must not contain credentials or provider payloads.
- Retention cleanup must be bounded and safe to run repeatedly. It must not delete the newest BlackBit/Winance observations or the current Money Storage/Sberkassa snapshots.
- The 30-day policy applies equally to the Python and JavaScript Cloudflare prototypes and any future production storage adapter.

## Current implementation gap

The current Python and JavaScript prototype migrations create an unbounded `quote_observations` table, and their scheduled handlers do not yet prune it. The policy above is therefore a requirement, not a claim that cleanup is already active. Before enabling production polling, implement and test 30-day pruning for BlackBit/Winance and separate replace-in-place storage for Money Storage/Sberkassa.
