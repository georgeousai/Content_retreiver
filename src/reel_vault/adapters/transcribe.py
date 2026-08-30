"""Speech-to-text for a downloaded reel, on Groq's free tier.

The downloaded mp4 is handed over whole rather than having its audio split
out first. Groq's transcription endpoint accepts mp4 directly, so a separate
extraction step would buy nothing and would put ffmpeg — a system binary, not
a Python dependency — between a saved reel and its transcript.
"""

from __future__ import annotations

import logging
from pathlib import Path

from groq import Groq

logger = logging.getLogger(__name__)

# Whisper large v3 turbo: the fastest of the free-tier transcription models,
# and the accuracy difference on a ninety-second reel does not pay for the
# slower one when every save queues another job behind it.
DEFAULT_MODEL = "whisper-large-v3-turbo"

# Groq rejects an oversized upload outright. A reel that large is not a reel;
# saying so in the log beats an opaque API error.
MAX_UPLOAD_BYTES = 24 * 1024 * 1024


class GroqTranscriber:
    def __init__(
        self, *, client: Groq | None = None, model: str = DEFAULT_MODEL
    ) -> None:
        self._client = client or Groq()
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
