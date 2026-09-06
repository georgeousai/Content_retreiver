"""Caption extraction: Instagram's oEmbed endpoint first, falling back to an
unofficial `yt-dlp`-based scrape (caption/description and author text only —
no video/audio is ever downloaded) if oEmbed fails or returns an unusable
caption."""

from __future__ import annotations

import logging

import httpx

from reel_vault.models import ExtractedPost

logger = logging.getLogger(__name__)

# The legacy, unauthenticated oEmbed endpoint. Measured live on 2026-08-31 it
# no longer serves JSON to anyone: it 301s to a trailing-slash form, then 302s,
# and answers 200 with Instagram's HTML login wall. Meta retired it in favour
# of `graph.facebook.com/<version>/instagram_oembed`, which needs an app token
# this project does not have. It is left in place — correctly handled rather
# than silently erroring — because it costs one request and would start
# working again the day a token is configured; in the meantime every caption
# in practice comes from the yt-dlp fallback below.
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
                OEMBED_URL,
                params={"url": url},
                timeout=self._timeout,
                # Instagram answers this endpoint with a 301 to a trailing-slash
                # form (and a 302 after that). httpx does not follow redirects
                # unless told to, and `raise_for_status` treats an unfollowed 3xx
                # as an error, so without this every oEmbed call failed on the
                # redirect and never reached the endpoint it was aimed at.
                follow_redirects=True,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.info("oEmbed fetch failed for %s: %s", url, exc)
            return None

        try:
            data = response.json()
        except ValueError:
            # A 200 carrying HTML is what this endpoint answers today (see
            # OEMBED_URL above), so it has to read as "oEmbed has nothing for
            # us" — the same as any other failure — and let the scraper
            # fallback run. Letting a JSONDecodeError out of here instead
            # would abort the whole save: nothing upstream catches it.
            logger.info(
                "oEmbed returned a non-JSON body for %s (content-type %s)",
                url,
                response.headers.get("content-type"),
            )
            return None

        if not isinstance(data, dict):
            # Valid JSON that is not an object — an error array, a bare
            # string. `.get` would raise on it, which lands in the same place
            # a JSONDecodeError would: out of the fetcher and into the save.
            logger.info("oEmbed returned an unexpected payload for %s", url)
            return None

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
