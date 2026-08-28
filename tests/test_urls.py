"""Unit tests for Instagram URL recognition/normalization.

Both `find_reel_url` (bot.py's "is this a link" gate) and `normalize_reel_url`
(the dedup key) are built on one regex now, after a live bug where they
disagreed: the gate rejected "instagram.com/<user>/reel/<code>/" while the
normalizer would have handled it fine. See .scratch/known-issues.md.
"""

from __future__ import annotations

import pytest

from reel_vault.urls import find_reel_url, normalize_reel_url

SHORTCODE_URLS = [
    "https://instagram.com/reel/DchAYCOtOI0/",
    "https://www.instagram.com/reel/DchAYCOtOI0/",
    "https://instagram.com/reels/DchAYCOtOI0/",
    "https://instagram.com/p/DchAYCOtOI0/",
    "https://instagram.com/tv/DchAYCOtOI0/",
    "https://instagram.com/ukjobsinsider/reel/DchAYCOtOI0/",
    "https://instagram.com/ukjobsinsider/p/DchAYCOtOI0/",
    "https://instagram.com/reel/DchAYCOtOI0/?igsh=abc123",
    "https://instagram.com/reel/DchAYCOtOI0",
]


@pytest.mark.parametrize("url", SHORTCODE_URLS)
def test_every_known_instagram_shape_is_recognized_as_a_reel_link(url: str) -> None:
    assert find_reel_url(url) is not None


@pytest.mark.parametrize("url", SHORTCODE_URLS)
def test_every_known_instagram_shape_normalizes_to_the_same_key(url: str) -> None:
    assert normalize_reel_url(url) == "https://instagram.com/p/DchAYCOtOI0"


def test_a_profile_scoped_reel_link_is_found_inside_a_longer_message() -> None:
    """The live failure: a profile-scoped share was rejected outright rather
    than being treated as an unrecognized link or a search query."""
    text = "check this out https://www.instagram.com/ukjobsinsider/reel/DchAYCOtOI0/ so good"
    found = find_reel_url(text)

    assert found is not None
    assert "DchAYCOtOI0" in found


def test_the_found_url_is_not_truncated_at_the_shortcode() -> None:
    """A regex that stops at the shortcode drops the trailing slash/query,
    so a caption fetcher keyed on the full URL then misses — this was a
    regression introduced while fixing the profile-scoped case above."""
    text = "https://www.instagram.com/p/DcellwxRN1m/"

    assert find_reel_url(text) == text


def test_a_profile_link_with_no_post_segment_is_not_a_reel_link() -> None:
    assert find_reel_url("https://www.instagram.com/some_profile/") is None


def test_an_unrelated_url_normalizes_via_the_generic_fallback() -> None:
    """Non-Instagram input (or an Instagram URL with no recognizable
    shortcode) still normalizes to *something* stable rather than raising,
    so a caller never has to pre-validate before calling."""
    assert normalize_reel_url("https://example.com/foo/?x=1") == "https://example.com/foo"
