"""Reading a reel's frames — the text on screen and what is being shown.

Also a `/chat/completions` call, with the frames attached as image parts.
That is the multimodal shape OpenAI defined and everyone else adopted,
including Google's compatibility endpoint, so this needs no vendor SDK of
its own and no second code path: which model looks at the frames is a base
URL, a key and a model name.

Every sampled frame goes into one request rather than one request per frame.
The frames are a sequence, and a list of text cards read together can be
reported in order and deduplicated; read one at a time they arrive as
unrelated fragments with the same header repeated on each.
"""

from __future__ import annotations

import base64
import logging

from openai import OpenAI
from openai.types.chat import (
    ChatCompletionContentPartParam,
    ChatCompletionUserMessageParam,
)

logger = logging.getLogger(__name__)

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


class VisionFrameAnalyzer:
    def __init__(self, *, client: OpenAI, model: str) -> None:
        self._client = client
        self._model = model

    def analyze(self, frames: list[bytes]) -> str:
        if not frames:
            return ""

        content: list[ChatCompletionContentPartParam] = [
            {"type": "text", "text": FRAME_PROMPT},
            *(_image_part(frame) for frame in frames),
        ]
        message: ChatCompletionUserMessageParam = {"role": "user", "content": content}
        response = self._client.chat.completions.create(
            model=self._model, messages=[message], temperature=0.0
        )
        return (response.choices[0].message.content or "").strip()


def _image_part(frame: bytes) -> ChatCompletionContentPartParam:
    """A frame as the chat API takes images: a data URI rather than a link.

    These frames exist only inside this call — they were decoded from a video
    that is deleted moments later — so there is nowhere to host them, and a
    URL would mean uploading images somewhere just to reference them back.
    """
    encoded = base64.b64encode(frame).decode()
    return {
        "type": "image_url",
        "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
    }
