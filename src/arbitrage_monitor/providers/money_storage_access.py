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


def is_money_storage_authenticated_offers_page(
    url: str, *, status: int | None, title: str = "", body: str = ""
) -> bool:
    """Require a successful protected offers document, not merely a provider URL."""
    return (
        classify_money_storage_page(url) == "deals"
        and status == 200
        and bool((title or "").strip())
        and len((body or "").strip()) >= 10
        and not is_money_storage_auth_failure(status=status, title=title, body=body)
    )


def has_returned_to_money_storage(url: str, *, eid_handoff_seen: bool) -> bool:
    """Return true for any HTTPS storage.money page reached after E-ID navigation."""
    parsed = urlparse(url)
    return (
        eid_handoff_seen
        and parsed.scheme == "https"
        and (parsed.hostname or "").lower() == "storage.money"
    )
