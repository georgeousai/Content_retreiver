"""Groq-backed adapters: open-vocabulary tagging, aggregate/single-item query
classification, and cross-caption summarization. All on Groq's free tier
using an open-weight model.

Groq's free-tier model lineup changes over time; the Llama-family chat
models the original spec called for have since been deprecated on Groq.
`openai/gpt-oss-20b` is the current open-weight equivalent. If this starts
404ing again, run `client.models.list()` to see what's currently available
and update DEFAULT_MODEL."""

from __future__ import annotations

import json
import logging

from groq import Groq

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "openai/gpt-oss-20b"

TAG_SYSTEM_PROMPT = (
    "You tag short social-media captions with topic keywords. Given a caption, "
    "reply with ONLY a JSON array of 1-5 short lowercase topic tags (single "
    "words or short phrases, no hashtags, no punctuation besides spaces/hyphens). "
    "Invent new tags freely; do not limit yourself to a fixed vocabulary. If the "
    "caption has no discernible topic, reply with an empty JSON array []."
)

INTENT_SYSTEM_PROMPT = (
    "You classify a user's request against a personal saved-content vault. "
    "Reply with ONLY the single word AGGREGATE if the request asks to gather, "
    "list, or summarize content across multiple saved items (e.g. 'give me all "
    "the X from my Y items', 'summarize my reels about Z'). Reply with ONLY the "
    "single word SINGLE if the request is looking for one specific saved item "
    "(e.g. 'find the reel about X')."
)

SUMMARY_SYSTEM_PROMPT = (
    "You answer a user's question using ONLY the provided captions from their "
    "saved reels. Synthesize a concise answer grounded in that content. Do not "
    "invent information not present in the captions."
)


class _GroqChatAdapter:
    """Shared request boilerplate for the Groq chat-completion adapters below."""

    def __init__(self, *, client: Groq | None = None, model: str = DEFAULT_MODEL) -> None:
        self._client = client or Groq()
        self._model = model

    def _complete(self, *, system_prompt: str, user_content: str, temperature: float) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=temperature,
        )
        return response.choices[0].message.content or ""


class GroqTagger(_GroqChatAdapter):
    def tag(self, caption: str) -> list[str]:
        content = self._complete(
            system_prompt=TAG_SYSTEM_PROMPT, user_content=caption, temperature=0.2
        )
        return _parse_tag_list(content or "[]")


class GroqQueryIntent(_GroqChatAdapter):
    def is_aggregate(self, query: str) -> bool:
        content = self._complete(
            system_prompt=INTENT_SYSTEM_PROMPT, user_content=query, temperature=0.0
        )
        return "AGGREGATE" in content.strip().upper()


class GroqSummarizer(_GroqChatAdapter):
    def summarize(self, query: str, captions: list[str]) -> str:
        captions_block = "\n\n".join(f"- {caption}" for caption in captions)
        user_content = f"Question: {query}\n\nCaptions:\n{captions_block}"
        return self._complete(
            system_prompt=SUMMARY_SYSTEM_PROMPT, user_content=user_content, temperature=0.3
        )


def _parse_tag_list(content: str) -> list[str]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("Groq tagger returned non-JSON content: %r", content)
        return []

    if not isinstance(parsed, list):
        return []
    return [str(tag).strip().lower() for tag in parsed if str(tag).strip()]
