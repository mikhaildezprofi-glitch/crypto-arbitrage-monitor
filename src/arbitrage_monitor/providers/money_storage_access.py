"""Pure state classifiers for Money Storage, E-ID, and Cloudflare navigation."""
from __future__ import annotations

from urllib.parse import urlparse


def classify_money_storage_page(url: str) -> str:
    """Return the provider route without guessing authentication state."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() != "storage.money":
        return "external"
    path = parsed.path.rstrip("/") or "/"
    if path == "/deals" and parsed.fragment == "tab-3":
        return "deals"
    if path == "/account":
        return "account"
    if path in ("/login", "/auth", "/signin"):
        return "login"
    return "other"


def is_money_storage_auth_failure(*, status: int | None, title: str = "", body: str = "") -> bool:
    """Identify an expired/rejected provider session from HTTP or visible page text."""
    if status in (401, 403):
        return True
    text = f"{title} {body}".lower()
    return any(marker in text for marker in (
        "session timed out",
        "you must log in",
        "please log in",
        "unauthenticated",
    ))


def classify_cloudflare_challenge(
    *,
    host: str,
    path: str,
    body: str,
    response_challenge: bool = False,
) -> bool:
    """Detect an actual challenge, not ordinary mentions of Cloudflare."""
    normalized_host = (host or "").lower()
    normalized_path = (path or "").lower()
    normalized_body = (body or "").lower()
    if response_challenge:
        return True
    if "/cdn-cgi/challenge-platform/" in normalized_path:
        return True
    if normalized_host == "challenges.cloudflare.com" or normalized_host.endswith(".challenges.cloudflare.com"):
        return True
    strong_markers = (
        "cf-turnstile",
        "turnstile",
        "checking your browser",
        "verify you are human",
        "attention required",
        "just a moment",
        "performing security verification",
        "enable javascript and cookies to continue",
    )
    return any(marker in normalized_body for marker in strong_markers)
