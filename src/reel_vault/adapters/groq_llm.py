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
import re
from collections.abc import Iterable

from groq import Groq

from reel_vault.models import (
    UNCATEGORIZED,
    CollectionAssignment,
    NeighbourPlacement,
    QueryClassification,
    QueryKind,
    SummarySource,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "openai/gpt-oss-20b"

TAG_SYSTEM_PROMPT = (
    "You tag short social-media captions with topic keywords. Given a caption, "
    "reply with ONLY a JSON array of 1-5 short lowercase topic tags (single "
    "words or short phrases, no hashtags, no punctuation besides spaces/hyphens). "
    "Invent new tags freely; do not limit yourself to a fixed vocabulary. If the "
    "caption has no discernible topic, reply with an empty JSON array []."
)

INTENT_SYSTEM_PROMPT = """\
You classify a user's request against a personal saved-content vault of \
social-media posts. Reply with ONLY a JSON object: \
{"kind": "...", "author": "..." or null, "collection": "..." or null}

The vault files every post under exactly one COLLECTION, and you are given the \
collections that currently exist. If the request names one of them - "my Sales \
reels", "everything in Fitness", "what do my AI reels say" - copy that \
collection's name EXACTLY into `collection`, matching it even when the user's \
capitalisation differs. A topic merely mentioned ("reels about biceps") is NOT \
a collection unless it matches an existing one by name. Otherwise `collection` \
is null.

`kind` is exactly one of:
- "AUTHOR_FILTER" - the user wants everything from one specific creator, \
identified by handle or name (e.g. "show me @gymshark's reels", "what have I \
saved from Andrew Huberman"). Put the creator, without a leading @, in `author`.
- "LIST" - the user wants to browse/see the saved items matching a topic, as a \
list (e.g. "show me all my reels about AI", "what reels do I have on sourdough").
- "AGGREGATE" - the user wants content gathered and synthesized ACROSS several \
saved items into a written answer (e.g. "give me all the interview questions \
from my AI reels", "summarize what my finance reels say about index funds").
- "SINGLE" - the user is looking for one specific saved item (e.g. "find that \
reel about transformer architecture").

LIST vs AGGREGATE is the key distinction: LIST hands back the items themselves, \
AGGREGATE reads them and writes an answer. `author` is null unless kind is \
AUTHOR_FILTER. `collection` is independent of `kind`: "show me my Sales reels" \
is LIST with collection "Sales"; "summarize my Sales reels" is AGGREGATE with \
collection "Sales"."""

SUMMARY_SYSTEM_PROMPT = """\
You answer a user's question using ONLY the provided captions from their \
saved reels. Each caption is labelled with the creator who posted it.

Write an answer, not an inventory. One line per reel saying what that reel is \
about is a table of contents, and the user is reading you precisely so they \
don't have to open the reels. Group the captions by what they actually say \
and let those shared points carry the structure. Where several creators make \
the same point, make it once and name them together.

Answer with the SUBSTANCE. If a caption lists four bicep hacks, name them; do \
not write "shares 4 bicep hacks".

Rules:
- Report only what the captions actually say. Never invent, and never guess at \
what the video shows - a caption is all you can see of its reel.
- Do not credit a caption with answering the question just because it shares a \
topic word with it. A caption mentioning "habits" is not thereby advice on \
"growing a personal brand" - it has to actually say so. Example: asked "how \
do I grow my personal brand", a caption reading "comment HABITS for my list \
of habits" does NOT support writing "a list of habits that can help grow \
your personal brand" - nothing in that caption makes that claim. The correct \
answer there is that none of the captions give direct advice on the question \
asked.
- Open with one or two sentences answering the question directly, before any \
heading or bullet.
- Group by theme by default. Group by creator only when the user asked who \
said what.
- SKIP any caption that does not address the question. A reel that merely \
carries a relevant hashtag adds nothing - leave it out rather than padding \
the answer with it.
- Attribute inline as "(@handle)", and only where knowing the source matters.
- A caption that is only a title with no substance ("Five Year Journey") has \
not earned a line of its own. Fold it into a theme or leave it out.
- If none of the captions really answer the question, say so plainly, and say \
that the content is likely spoken in the videos rather than written in the \
captions.

Formatting - your reply is rendered in a chat app that supports NOTHING but \
these two markers:
- A section heading is a line starting with "## ". Use at most three, and only \
when the answer genuinely has sections; a short answer needs none.
- A bullet is a line starting with "- ".
Write everything else as plain sentences. Do NOT use tables, pipes, asterisks, \
underscores, backticks, or "#" for anything else - they reach the user \
literally."""


COLLECTION_SYSTEM_PROMPT = (
    "You file a saved social-media post into a personal library. You are given "
    "the post's caption, the library's EXISTING collections (each with its "
    "existing sub-collections), and the posts already in the library whose "
    "captions most resemble this one, with where each of those was filed.\n\n"
    "Rules, in priority order:\n"
    f"1. First judge whether the caption itself carries enough real subject "
    f"matter to determine a topic. Generic hooks, reaction lines, dates, or "
    f"vague teasers (e.g. \"5 years ago this wasn't a thing\", \"wait for it\", "
    f"\"POV:\") carry NO topic on their own, even if the video behind them "
    f"might. If that is all you have, respond with "
    f'{{"collection": "{UNCATEGORIZED}", "subcollection": null}} — do NOT pick '
    f"an existing collection just because one happens to exist. Guessing a "
    f"specific-sounding topic from a caption that does not support it is "
    f"worse than admitting you don't know.\n"
    "2. Otherwise, STRONGLY prefer reusing an existing collection that "
    "actually matches the caption's real content. Only invent a new one if "
    "the caption clearly does not belong in any existing one.\n"
    "2b. Weigh the SIMILAR POSTS heavily: they show where this library "
    "actually puts posts like this one, which the collection names alone "
    "cannot tell you. A similar post marked [user-placed] was filed by the "
    "user personally and is stronger evidence than one this classifier "
    "placed unaided - where they disagree, follow the user. But similar "
    "WORDING is not the same as the same TOPIC: a neighbour is evidence to "
    "weigh, never an instruction to copy, and a caption that plainly "
    "belongs elsewhere goes elsewhere.\n"
    "2c. Do NOT let a sub-collection name pull a post onto the wrong "
    "collection. Matching a narrow name is not a reason to file a post on a "
    "shelf whose subject it does not share.\n"
    "3. Give it a sub-collection whenever the caption's content is specific "
    "enough to name one narrower than the collection itself (e.g. \"Bicep "
    "Workouts\" under \"Fitness\", \"Cold Outreach\" under \"Sales\") — do "
    "not leave it null purely because none exist yet for that collection; "
    "you invent the first one the same way you invented the collection. "
    "Reuse an existing sub-collection over inventing a near-duplicate. Use "
    "null only when the caption's topic really is no narrower than the "
    "collection as a whole.\n"
    "4. Collection names are short Title Case noun phrases (e.g. \"AI\", "
    "\"Fitness\", \"Personal Finance\").\n"
    "5. Never rename or re-word an existing collection: copy it exactly.\n\n"
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
    def classify(self, query: str, collections: list[str]) -> QueryClassification:
        existing = ", ".join(sorted(collections)) if collections else "(none yet)"
        content = self._complete(
            system_prompt=INTENT_SYSTEM_PROMPT,
            user_content=f"Existing collections: {existing}\n\nRequest:\n{query}",
            temperature=0.0,
        )
        return _parse_classification(content, collections)


class GroqCollectionAssigner(_GroqChatAdapter):
    def assign(
        self,
        caption: str,
        known: dict[str, list[str]],
        neighbours: list[NeighbourPlacement],
    ) -> CollectionAssignment:
        known_block = (
            json.dumps(known, indent=2) if known else "(none yet — this is the first post)"
        )
        content = self._complete(
            system_prompt=COLLECTION_SYSTEM_PROMPT,
            user_content=(
                f"Existing collections:\n{known_block}\n\n"
                f"Similar posts already in the library:\n"
                f"{_format_neighbours(neighbours)}\n\n"
                f"Caption:\n{caption}"
            ),
            temperature=0.0,
        )
        return _parse_assignment(content, known)


class GroqSummarizer(_GroqChatAdapter):
    def summarize(self, query: str, sources: list[SummarySource]) -> str:
        captions_block = "\n\n".join(_format_source(source) for source in sources)
        user_content = f"Question: {query}\n\nCaptions:\n{captions_block}"
        return self._complete(
            system_prompt=SUMMARY_SYSTEM_PROMPT, user_content=user_content, temperature=0.3
        )


def _format_neighbours(neighbours: list[NeighbourPlacement]) -> str:
    """The similar posts, each with where it was filed and by whom.

    A placement the user made is labelled as such: the model is told to
    prefer it over one the classifier made unaided, so that a mistake this
    classifier already made cannot quietly become the precedent for the next
    reel that resembles it.
    """
    if not neighbours:
        return "(none yet — this is the first post)"
    lines = []
    for neighbour in neighbours:
        where = neighbour.collection
        if neighbour.subcollection:
            where = f"{where} > {neighbour.subcollection}"
        who = " [user-placed]" if neighbour.user_placed else ""
        lines.append(
            f'- filed under {where}{who} (similarity {neighbour.similarity:.2f}): '
            f'"{neighbour.caption[:160]}"'
        )
    return "\n".join(lines)


def _format_source(source: SummarySource) -> str:
    """Label each caption with its creator, so the model can attribute. An
    unknown creator is said to be unknown rather than left blank, which the
    model could otherwise read as the previous caption's author."""
    if source.author_handle and source.author_name:
        who = f"{source.author_name} (@{source.author_handle})"
    else:
        who = source.author_handle or source.author_name or "unknown creator"
    return f"- [by {who}] {source.caption}"


def _loads_json(content: str) -> object | None:
    """Parse a model's JSON reply, tolerating the ```json fences and stray
    preamble chat models wrap answers in. Returns None if nothing parses.

    Being strict here is expensive: an unparsed reply is not an error the
    user ever sees, it is silently the wrong answer shape."""
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(.+?)```", content, re.DOTALL)
    candidates = [fenced.group(1)] if fenced else []
    # Fall back to the outermost object/array anywhere in the reply.
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = content.find(opener), content.rfind(closer)
        if start != -1 and end > start:
            candidates.append(content[start : end + 1])

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _parse_classification(
    content: str, collections: list[str] | None = None
) -> QueryClassification:
    """Parse the classifier's JSON. Anything unparseable falls back to SINGLE —
    the narrowest, cheapest answer shape, and the one the vault has always
    defaulted to."""
    parsed = _loads_json(content)
    if parsed is None:
        logger.warning("Query classifier returned non-JSON content: %r", content)
        return QueryClassification(kind=QueryKind.SINGLE)

    if not isinstance(parsed, dict):
        return QueryClassification(kind=QueryKind.SINGLE)

    raw_kind = str(parsed.get("kind") or "").strip().upper()
    try:
        kind = QueryKind[raw_kind]
    except KeyError:
        logger.warning("Query classifier returned unknown kind: %r", raw_kind)
        return QueryClassification(kind=QueryKind.SINGLE)

    raw_author = parsed.get("author")
    author = str(raw_author).strip().lstrip("@") or None if raw_author else None
    if kind is not QueryKind.AUTHOR_FILTER:
        author = None
    elif author is None:
        # An author filter with nobody to filter on is not actionable; the
        # semantic path at least stands a chance of matching the handle text.
        logger.warning("Author-filter classification carried no author: %r", content)
        return QueryClassification(kind=QueryKind.LIST)

    raw_collection = parsed.get("collection")
    collection = str(raw_collection).strip() if raw_collection else None
    if collection:
        # Only a collection the vault actually holds can be filtered on; a
        # near-miss name is snapped back onto the real one, and anything
        # invented is dropped so retrieval falls back to semantic search.
        collection = _match_collection(collection, collections or [])

    return QueryClassification(kind=kind, author=author, collection=collection)


def _match_collection(name: str, collections: list[str]) -> str | None:
    for candidate in collections:
        if candidate.casefold() == name.casefold():
            return candidate
    logger.info("Classifier named an unknown collection: %r", name)
    return None


def _parse_assignment(content: str, known: dict[str, list[str]]) -> CollectionAssignment:
    """Parse the model's JSON, then snap near-miss names back onto existing
    collections so casing/whitespace drift can't fork a duplicate collection."""
    parsed = _loads_json(content)
    if parsed is None:
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
    parsed = _loads_json(content)
    if parsed is None:
        logger.warning("Groq tagger returned non-JSON content: %r", content)
        return []

    if not isinstance(parsed, list):
        return []
    return [str(tag).strip().lower() for tag in parsed if str(tag).strip()]
