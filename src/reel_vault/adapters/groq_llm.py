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
from collections.abc import Iterable

from groq import Groq

from reel_vault.models import UNCATEGORIZED, CollectionAssignment

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

COLLECTION_SYSTEM_PROMPT = (
    "You file a saved social-media post into a personal library. You are given "
    "the post's caption and the library's EXISTING collections (each with its "
    "existing sub-collections).\n\n"
    "Rules:\n"
    "1. STRONGLY prefer reusing an existing collection. Only invent a new one "
    "if the caption genuinely does not belong in any of them.\n"
    "2. Reuse an existing sub-collection where one fits. A sub-collection is "
    "optional — use null when the collection alone is specific enough.\n"
    "3. Collection names are short Title Case noun phrases (e.g. \"AI\", "
    "\"Fitness\", \"Personal Finance\").\n"
    "4. Never rename or re-word an existing collection: copy it exactly.\n\n"
    'Reply with ONLY a JSON object: {"collection": "...", "subcollection": '
    '"..." or null}'
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


class GroqCollectionAssigner(_GroqChatAdapter):
    def assign(
        self, caption: str, known: dict[str, list[str]]
    ) -> CollectionAssignment:
        known_block = (
            json.dumps(known, indent=2) if known else "(none yet — this is the first post)"
        )
        content = self._complete(
            system_prompt=COLLECTION_SYSTEM_PROMPT,
            user_content=f"Existing collections:\n{known_block}\n\nCaption:\n{caption}",
            temperature=0.0,
        )
        return _parse_assignment(content, known)


class GroqSummarizer(_GroqChatAdapter):
    def summarize(self, query: str, captions: list[str]) -> str:
        captions_block = "\n\n".join(f"- {caption}" for caption in captions)
        user_content = f"Question: {query}\n\nCaptions:\n{captions_block}"
        return self._complete(
            system_prompt=SUMMARY_SYSTEM_PROMPT, user_content=user_content, temperature=0.3
        )


def _parse_assignment(content: str, known: dict[str, list[str]]) -> CollectionAssignment:
    """Parse the model's JSON, then snap near-miss names back onto existing
    collections so casing/whitespace drift can't fork a duplicate collection."""
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("Collection assigner returned non-JSON content: %r", content)
        return CollectionAssignment(collection=UNCATEGORIZED)

    if not isinstance(parsed, dict):
        return CollectionAssignment(collection=UNCATEGORIZED)

    collection = str(parsed.get("collection") or "").strip() or UNCATEGORIZED
    raw_sub = parsed.get("subcollection")
    subcollection = str(raw_sub).strip() if raw_sub else None

    collection = _canonicalize(collection, known.keys())
    if subcollection:
        subcollection = _canonicalize(subcollection, known.get(collection, []))
    return CollectionAssignment(collection=collection, subcollection=subcollection)


def _canonicalize(name: str, existing: Iterable[str]) -> str:
    """Return the existing spelling of `name` if one matches case-insensitively."""
    for candidate in existing:
        if candidate.casefold() == name.casefold():
            return candidate
    return name


def _parse_tag_list(content: str) -> list[str]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("Groq tagger returned non-JSON content: %r", content)
        return []

    if not isinstance(parsed, list):
        return []
    return [str(tag).strip().lower() for tag in parsed if str(tag).strip()]
