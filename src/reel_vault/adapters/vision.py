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

from reel_vault.adapters.llm import content_of

logger = logging.getLogger(__name__)

FRAME_PROMPT = """\
These are still frames sampled in order from one short vertical social-media \
video. Report what the video shows.

Transcribe the text this video is carrying, exactly as written, in the order \
the frames appear. That text is the point of this task: these videos often \
carry their whole content on screen, and a missed line is content lost. It \
counts wherever it is written:
- text cards and title slides;
- captions and labels burned into the frame;
- handwriting and diagram labels, on a whiteboard, a notebook, a slide or a \
shared screen.

A diagram is text to read, not scenery to describe. Transcribe its labels, \
grouped per board or per diagram, rather than reporting that a diagram is \
being drawn.

Then, in one or two sentences, say what is physically happening on screen \
(who or what is shown, what they are doing, the setting).

Rules:
- Transcribe the text that belongs to what this video is presenting - the \
cards it shows, the board being explained, the slide or screen being shared. \
Text that is only along for the ride gets ONE line naming what it is, and \
none of its own words: a poster on the wall behind the speaker, a browser \
tab, an app's own buttons and menus, and pasted-in screenshots of something \
the video is not about, such as a testimonial, a comment section, a chat, or \
someone else's post. Worked example: a video explaining two AI architectures \
on whiteboards pastes a screenshot of a stranger's job-offer post over the \
middle of the frame for a few seconds. The whole correct output for it is \
one line - "overlay: a screenshot of a social post about a job offer" - and \
not a word of the post itself. Transcribed in full, that post was the \
largest block in this video's entire reading: paragraphs about a delivery \
company's hiring process, and nothing about the architectures the video \
actually teaches.
- Never guess at an unclear value. Where a number, name or word is too \
small, too blurred or cut off to read with confidence, write "(illegible)" \
in its place. Do not supply a plausible one, and do not tidy several \
figures into a round total. Worked example: a frame reading "Base: 145k, \
Signing bonus: 20k, Relocation: 3k, Stock: 90k" was reported as round \
six-figure sums attached to the wrong labels - not one of those numbers was \
on screen. An invented number is indistinguishable from a real one once it \
has been written down, and the neater it looks the more likely it is that \
you supplied it rather than read it.
- Report only what is visible. Never guess at what happens between frames, \
and never infer what is being said aloud - you cannot hear this video.
- If the same text appears in several frames, write it once.
- If a frame is a transition, blur, or blank, skip it rather than describing it.
- No preamble and no closing remark. Start with the text you read."""


class VisionFrameAnalyzer:
    """The one model call in this app that cannot go through `_ChatAdapter`:
    it sends image parts and no system prompt. It reads its reply through the
    same `content_of` all the others do, which is the part that matters --
    being outside `_complete` is how this adapter went through an audit of
    every truncating call site without being counted, and the default vision
    model is a reasoning model, so it fails exactly the same way.

    An empty frame reading is meaningful here, so a truncated one is raised
    rather than returned. `VideoMediaExtractor` catches it and records the
    frames as unread; returning "" would have filed the reel as read with
    nothing on screen, and nothing would ever have looked again.
    """

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
        return content_of(
            response,
            model=self._model,
            context=f"{len(frames)} frames",
            empty_reply_is_meaningful=True,
        ).strip()


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
