"""Caption extraction: Instagram's oEmbed endpoint first, falling back to an
unofficial `yt-dlp`-based scrape (caption/description text only — no
video/audio is ever downloaded) if oEmbed fails or returns an unusable
caption."""

from __future__ import annotations

import logging

import httpx

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

    def fetch(self, url: str) -> str | None:
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
        return caption if _usable(caption) else None


class YtDlpCaptionFetcher:
    """Extracts only the post description/caption via yt-dlp's metadata
    extraction — `download=False`, no media is ever fetched."""

    def fetch(self, url: str) -> str | None:
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

        caption = (info or {}).get("description")
        return caption if _usable(caption) else None


class CompositeCaptionFetcher:
    """Tries each fetcher in order, returning the first usable caption."""

    def __init__(self, fetchers: list) -> None:
        self._fetchers = fetchers

    def fetch(self, url: str) -> str | None:
        for fetcher in self._fetchers:
            caption = fetcher.fetch(url)
            if _usable(caption):
                return caption
        return None
