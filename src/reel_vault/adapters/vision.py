"""Reading a reel's frames — the text on screen and what is being shown — via
Gemini Flash's free tier.

Every sampled frame goes into one request rather than one request per frame.
The frames are a sequence, and a list of text cards read together can be
reported in order and deduplicated; read one at a time they arrive as
unrelated fragments with the same header repeated on each.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"

FRAME_PROMPT = """\
These are still frames sampled in order from one short vertical social-media \
video. Report what the video shows.

Transcribe EVERY piece of on-screen text exactly as written, in the order the \
frames appear. On-screen text is the point of this task: these videos often \
carry their whole content as text cards, and a missed card is content lost.

Then, in one or two sentences, say what is physically happening on screen \
(who or what is shown, what they are doing, the setting).

Rules:
- Report only what is visible. Never guess at what happens between frames, \
and never infer what is being said aloud - you cannot hear this video.
- If the same text card appears in several frames, write it once.
- If a frame is a transition, blur, or blank, skip it rather than describing it.
- No preamble and no closing remark. Start with the text you read."""


class GeminiFrameAnalyzer:
    def __init__(self, api_key: str, *, model: str = DEFAULT_MODEL) -> None:
        self._api_key = api_key
        self._model = model
        self._client = None

    def analyze(self, frames: list[bytes]) -> str:
        if not frames:
            return ""

        from google.genai import types

        client = self._ensure_client()
        parts = [
            types.Part.from_bytes(data=frame, mime_type="image/jpeg")
            for frame in frames
        ]
        response = client.models.generate_content(
            model=self._model, contents=[FRAME_PROMPT, *parts]
        )
        return (getattr(response, "text", "") or "").strip()

    def _ensure_client(self):
        """Built on first use, not in __init__: this adapter is constructed
        at startup for every run, and a vision client is only ever needed by
        a background job that may not happen for hours."""
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self._api_key)
        return self._client
