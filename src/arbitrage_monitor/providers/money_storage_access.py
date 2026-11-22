"""Pure state classifiers for Money Storage, E-ID, and Cloudflare navigation."""
from __future__ import annotations

from urllib.parse import urlparse


def classify_money_storage_page(url: str) -> str:
    """Return the authenticated provider landing route without guessing auth state."""
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


def classify_cloudflare_challenge(
    *,
    host: str,
    path: str,
    body: str,
    response_challenge: bool = False,
) -> bool:
    """Detect a visible Cloudflare challenge independently of E-ID routing."""
    normalized_host = (host or "").lower()
    normalized_path = (path or "").lower()
    normalized_body = (body or "").lower()
    if response_challenge:
        return True
    if "/cdn-cgi/challenge-platform/" in normalized_path:
        return True
    markers = (
        "cf-turnstile",
        "turnstile",
        "checking your browser",
        "verify you are human",
        "attention required",
        "cloudflare",
        "captcha",
    )
    if any(marker in normalized_body for marker in markers):
        return True
    return normalized_host.startswith("challenges.cloudflare.com")
