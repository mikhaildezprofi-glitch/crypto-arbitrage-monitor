"""Common read-only interface for market quote providers."""

from __future__ import annotations

from typing import Protocol

from ..models import Quote


class QuoteProvider(Protocol):
    """Structural interface implemented by each exchange/source adapter."""

    def fetch_quote(self) -> Quote:
        """Fetch one current quote without placing or modifying any orders."""
        ...


class ProviderCollectionError(RuntimeError):
    """Raised when provider collection cannot produce a complete quote set."""
