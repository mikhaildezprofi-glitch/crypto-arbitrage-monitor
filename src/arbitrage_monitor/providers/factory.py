"""Build the complete five-source provider set from live APIs and fresh snapshots."""
from __future__ import annotations

import os

from .blackbit import BlackBitQuoteProvider
from .money_storage import MoneyStorageSnapshotQuoteProvider
from .sberkassa import (
    SberkassaExchangeSnapshotQuoteProvider,
    SberkassaSnapshotQuoteProvider,
)
from .winance import WinanceQuoteProvider


def build_default_providers() -> dict:
    """Return all five required providers; snapshot paths may be overridden by env.

    Browser-authenticated providers consume only sanitized artifacts produced
    by the approved cloud browser workflows. Missing artifacts fail closed.
    """
    return {
        "money_storage": MoneyStorageSnapshotQuoteProvider(
            os.getenv("MONEY_STORAGE_SNAPSHOT_PATH", "money-storage-current-offers.json")
        ),
        "blackbit": BlackBitQuoteProvider(),
        "winance": WinanceQuoteProvider(),
        "sberkassa_sell": SberkassaSnapshotQuoteProvider(
            os.getenv("SBERKASSA_SELL_SNAPSHOT_PATH", "sberkassa-current-inspection.json")
        ),
        "sberkassa_exchange": SberkassaExchangeSnapshotQuoteProvider(
            os.getenv("SBERKASSA_EXCHANGE_SNAPSHOT_PATH", "sberkassa-exchange-inspection.json")
        ),
    }
