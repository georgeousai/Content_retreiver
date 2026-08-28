"""Recognizing and normalizing Instagram post/reel URLs.

One regex, used both to decide "is this a link we can save" and to compute
the duplicate-detection key, so the two questions can't drift apart (they
did once — see .scratch/known-issues.md, "URL matcher and dedup key
disagree").
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

# Every Instagram permalink shape converges on the same thing: a shortcode.
# The only thing that varies is the decoration around it —
#   instagram.com/reel/<code>/
#   instagram.com/reels/<code>/
#   instagram.com/p/<code>/           (Instagram's universal permalink —
#                                       opens reels, photos, and carousels)
#   instagram.com/tv/<code>/          (legacy IGTV; still resolves)
#   instagram.com/<username>/reel/<code>/   (shared from a profile page)
#   instagram.com/<username>/p/<code>/
# The optional username segment is what a plain "(?:reel|reels|p|tv)/"
# pattern misses, which is what let "instagram.com/<user>/reel/<code>/"
# through as unrecognized.
INSTAGRAM_POST_URL = re.compile(
    r"https?://(?:www\.)?instagram\.com/"
    r"(?:[A-Za-z0-9_.]+/)?"
    r"(?:reel|reels|p|tv)/"
    r"(?P<shortcode>[\w-]+)"
    # A trailing slash and/or query string (tracking params like ?igsh=...)
    # are not part of the shortcode but are part of the URL text a caller
    # like `find_reel_url` needs back whole, not truncated at the shortcode.
    r"/?\S*",
    re.IGNORECASE,
)

INSTAGRAM_URL = re.compile(r"https?://(?:www\.)?instagram\.com/\S*", re.IGNORECASE)


def shortcode_of(url: str) -> str | None:
    """Instagram's own identifier for a post, or None if this isn't one."""
    match = INSTAGRAM_POST_URL.search(url.strip())
    return match["shortcode"] if match else None


def url_for_shortcode(shortcode: str) -> str:
    """The canonical URL carrying a shortcode — the inverse of `shortcode_of`.

    Used where a reel's identity has to travel somewhere too small for a URL:
    a Telegram callback allows 64 bytes for everything it carries, and the
    shortcode is the only part of the URL that means anything anyway.
    """
    return f"https://instagram.com/p/{shortcode}"


def find_reel_url(text: str) -> str | None:
    """The first recognizable Instagram post/reel link in `text`, or None."""
    match = INSTAGRAM_POST_URL.search(text)
    return match.group(0) if match else None


def normalize_reel_url(url: str) -> str:
    """The duplicate-detection key: Instagram's shortcode is the reel's real
    identity, so every URL shape that carries the same shortcode normalizes
    to the same key — `/reel/`, `/p/`, `/tv/`, and the `/<username>/...`
    variants of each all collapse together.

    `/p/` is used as the canonical form since it is Instagram's universal
    permalink and reliably reopens the post regardless of which shape it
    was originally shared as (spec user story 9: the bot must be able to
    hand the link back to reopen in Instagram).

    A string that doesn't match a known Instagram shape falls back to the
    old scheme/host/trailing-slash collapse, so a caller does not have to
    pre-validate before normalizing.
    """
    code = shortcode_of(url)
    if code:
        return url_for_shortcode(code)

    parts = urlsplit(url.strip())
    host = (parts.netloc or "").lower().removeprefix("www.")
    path = parts.path.rstrip("/")
    return f"https://{host}{path}"
