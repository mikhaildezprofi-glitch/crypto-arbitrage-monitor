#!/usr/bin/env python3
"""Check the cloud runner's UTC clock against independent HTTPS Date headers.

This is only a clock-alignment check. HTTP headers are never used as quote
freshness timestamps or as evidence that a provider refreshed its offers.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.error import URLError
from urllib.request import Request, urlopen

SOURCES = (
    "https://www.google.com/generate_204",
    "https://www.apple.com/",
    "https://www.cloudflare.com/",
    "https://www.microsoft.com/",
)
MAX_OFFSET_SECONDS = 5.0
MAX_SPREAD_SECONDS = 2.0
RETRIES_PER_SOURCE = 2


def main() -> int:
    offsets: list[float] = []
    for url in SOURCES:
        last_error = "no response"
        for attempt in range(1, RETRIES_PER_SOURCE + 1):
            nonce = str(time.time_ns())
            request = Request(
                f"{url}?clock_check={nonce}",
                method="HEAD",
                headers={"Cache-Control": "no-cache, no-store", "Pragma": "no-cache"},
            )
            before = time.time()
            try:
                with urlopen(request, timeout=5) as response:
                    raw_date = response.headers.get("Date")
                after = time.time()
                if not raw_date:
                    raise ValueError("missing HTTP Date header")
                server_time = parsedate_to_datetime(raw_date).astimezone(timezone.utc).timestamp()
                offset = server_time - ((before + after) / 2)
                offsets.append(offset)
                print(
                    f"CLOCK_REFERENCE={url} OFFSET_SECONDS={offset:.3f} "
                    f"RTT_SECONDS={after-before:.3f} ATTEMPT={attempt}"
                )
                break
            except Exception as exc:
                last_error = type(exc).__name__
                if attempt == RETRIES_PER_SOURCE:
                    print(f"CLOCK_REFERENCE={url} STATUS=UNAVAILABLE REASON={last_error}")
                else:
                    time.sleep(0.5)

    if len(offsets) < 2:
        raise SystemExit("Fewer than two independent HTTPS time references responded.")
    if max(abs(value) for value in offsets) > MAX_OFFSET_SECONDS:
        raise SystemExit("Runner clock differs from external UTC references by more than 5 seconds.")
    if max(offsets) - min(offsets) > MAX_SPREAD_SECONDS:
        raise SystemExit("External UTC references disagree by more than 2 seconds.")

    print(f"RUNNER_CLOCK_ALIGNMENT=CONFIRMED REFERENCES={len(offsets)}")
    print(datetime.now(timezone.utc).isoformat())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
