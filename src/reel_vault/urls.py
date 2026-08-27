"""Normalization for Instagram Reel URLs used as the duplicate-detection key."""

from __future__ import annotations

from urllib.parse import urlsplit


def normalize_reel_url(url: str) -> str:
    """Collapse tracking params, host casing, and trailing-slash variants so
    the same reel shared twice normalizes to the same key, while remaining a
    valid, openable `https://instagram.com/...` link (spec user story 9:
    the bot must be able to hand the original link back to reopen in
    Instagram).

    e.g. "https://www.instagram.com/reel/ABC123/?igsh=xyz" and
    "instagram.com/reel/ABC123" both normalize to
    "https://instagram.com/reel/ABC123".

    The path's shortcode segment is case-sensitive on Instagram and is left
    as-is; only the scheme, host casing/`www.` prefix, and query
    string/trailing slash are collapsed.
    """
    parts = urlsplit(url.strip())
    host = (parts.netloc or "").lower().removeprefix("www.")
    path = parts.path.rstrip("/")
    return f"https://{host}{path}"
