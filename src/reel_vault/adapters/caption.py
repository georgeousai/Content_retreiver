"""Caption extraction: Instagram's oEmbed endpoint first, falling back to an
unofficial `yt-dlp`-based scrape (caption/description and author text only —
no video/audio is ever downloaded) if oEmbed fails or returns an unusable
caption."""

from __future__ import annotations

import logging

import httpx

from reel_vault.models import ExtractedPost

logger = logging.getLogger(__name__)

OEMBED_URL = "https://api.instagram.com/oembed"


def _looks_truncated(caption: str) -> bool:
    stripped = caption.strip()
    return stripped.endswith("…") or stripped.endswith("...")


def _usable(caption: str | None) -> bool:
    return bool(caption and caption.strip() and not _looks_truncated(caption))


class OEmbedCaptionFetcher:
    def __init__(self, *, timeout: float = 10.0) -> None:
        self._timeout = timeout

    def fetch(self, url: str) -> ExtractedPost | None:
        try:
            response = httpx.get(
                OEMBED_URL, params={"url": url}, timeout=self._timeout
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.info("oEmbed fetch failed for %s: %s", url, exc)
            return None

        data = response.json()
        caption = data.get("title")
        if not isinstance(caption, str) or not _usable(caption):
            return None
        return ExtractedPost(
            caption=caption,
            author_handle=data.get("author_name"),
            author_name=data.get("author_name"),
            thumbnail_url=data.get("thumbnail_url"),
        )


class YtDlpCaptionFetcher:
    """Extracts only the post description/caption and author via yt-dlp's
    metadata extraction — `download=False`, no media is ever fetched."""

    def fetch(self, url: str) -> ExtractedPost | None:
        try:
            import yt_dlp
        except ImportError:  # pragma: no cover - dependency is always installed
            logger.warning("yt-dlp is not installed; skipping scraper fallback")
            return None

        options = {"quiet": True, "skip_download": True, "no_warnings": True}
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as exc:  # yt-dlp raises its own broad DownloadError
            logger.info("yt-dlp fetch failed for %s: %s", url, exc)
            return None

        info = info or {}
        caption = info.get("description")
        if not isinstance(caption, str) or not _usable(caption):
            return None
        return ExtractedPost(
            caption=caption,
            # `channel` is the @handle (e.g. "bashi_fuirkashi"); `uploader` is
            # the display name (e.g. "Bashiri Smith").
            author_handle=info.get("channel") or info.get("uploader_id"),
            author_name=info.get("uploader"),
            thumbnail_url=info.get("thumbnail"),
        )


class CompositeCaptionFetcher:
    """Tries each fetcher in order, returning the first usable result."""

    def __init__(self, fetchers: list) -> None:
        self._fetchers = fetchers

    def fetch(self, url: str) -> ExtractedPost | None:
        for fetcher in self._fetchers:
            post = fetcher.fetch(url)
            if post is not None and _usable(post.caption):
                return post
        return None
