"""Speech-to-text for a downloaded reel.

One call to `/audio/transcriptions` — the same OpenAI-compatible shape the
chat adapters use, so which provider hears the reel is a base URL, a key and
a model name, not a code path.

The downloaded mp4 is handed over whole rather than having its audio split
out first. The endpoint accepts mp4 directly, so a separate extraction step
would buy nothing and would put ffmpeg — a system binary, not a Python
dependency — between a saved reel and its transcript.
"""

from __future__ import annotations

import logging
from pathlib import Path

from openai import OpenAI

logger = logging.getLogger(__name__)

# Providers reject an oversized upload outright. A reel that large is not a
# reel; saying so in the log beats an opaque API error.
MAX_UPLOAD_BYTES = 24 * 1024 * 1024


class AudioTranscriber:
    def __init__(self, *, client: OpenAI, model: str) -> None:
        self._client = client
        self._model = model

    def transcribe(self, media_path: Path) -> str:
        size = media_path.stat().st_size
        if size > MAX_UPLOAD_BYTES:
            logger.info(
                "Skipping transcription of %s: %d bytes exceeds the upload limit",
                media_path.name,
                size,
            )
            return ""

        with media_path.open("rb") as media:
            response = self._client.audio.transcriptions.create(
                file=(media_path.name, media.read()),
                model=self._model,
            )
        return (getattr(response, "text", "") or "").strip()
