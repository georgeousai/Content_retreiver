"""Thumbnail storage backed by Telegram itself.

Instagram's thumbnail URLs are signed and expire, so persisting one means a
reel saved today shows a broken image months from now. Telegram, on the other
hand, hands back a `file_id` for any photo it has seen, that never expires and
costs nothing to re-send — which makes the bot we already talk to a perfectly
good free image host.

The upload message is deleted immediately: it exists only to mint the
`file_id`, which stays valid afterwards, so the user's chat isn't littered
with pictures they didn't ask for.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"


class TelegramThumbnailStore:
    """Uploads by URL — Telegram fetches the image server-side, so the reel's
    picture never has to pass through this process."""

    def __init__(self, token: str, chat_id: str | int, *, timeout: float = 20.0) -> None:
        self._token = token
        self._chat_id = chat_id
        self._timeout = timeout

    def store(self, thumbnail_url: str) -> str | None:
        response = httpx.post(
            f"{API_BASE}/bot{self._token}/sendPhoto",
            data={"chat_id": self._chat_id, "photo": thumbnail_url},
            timeout=self._timeout,
        )
        response.raise_for_status()
        result = response.json().get("result") or {}

        file_id = _largest_photo_file_id(result.get("photo") or [])
        if file_id is None:
            logger.warning("sendPhoto returned no photo sizes for %s", thumbnail_url)
            return None

        self._delete(result.get("message_id"))
        return file_id

    def _delete(self, message_id: int | None) -> None:
        """Best-effort: a leftover upload message is untidy, not broken, and
        must never cost us the file_id we just minted."""
        if message_id is None:
            return
        try:
            httpx.post(
                f"{API_BASE}/bot{self._token}/deleteMessage",
                data={"chat_id": self._chat_id, "message_id": message_id},
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            logger.info("Could not delete thumbnail upload message: %s", exc)


def _largest_photo_file_id(sizes: list[dict]) -> str | None:
    """Telegram returns one entry per rendered size; the largest is the one
    worth keeping."""
    best = None
    for size in sizes:
        file_id = size.get("file_id")
        if not file_id:
            continue
        area = int(size.get("width") or 0) * int(size.get("height") or 0)
        if best is None or area > best[0]:
            best = (area, file_id)
    return best[1] if best else None
