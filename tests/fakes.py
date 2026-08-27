"""Fake adapters for exercising `Vault` without any real network/LLM/DB calls,
per the spec's testing decisions (tests target the seam, not the adapters)."""

from __future__ import annotations

import math
import re
import zlib
from collections.abc import Mapping

from reel_vault.models import (
    CollectionAssignment,
    ExtractedPost,
    QueryClassification,
    QueryKind,
    SavedReel,
    SummarySource,
)
from reel_vault.urls import normalize_reel_url


class FakeCaptionFetcher:
    """Maps URL -> ExtractedPost. A missing/None entry simulates extraction
    failure. Plain strings are accepted as a shorthand for a caption with no
    author attached."""

    def __init__(self, posts: Mapping[str, ExtractedPost | str | None]) -> None:
        self._posts = posts

    def fetch(self, url: str) -> ExtractedPost | None:
        post = self._posts.get(url)
        if post is None:
            return None
        if isinstance(post, str):
            return ExtractedPost(caption=post)
        return post


class FakeTagger:
    """Deterministic tagger: splits on a caller-supplied mapping, defaulting
    to a single tag derived from the caption's first word."""

    def __init__(self, tags_by_caption: dict[str, list[str]] | None = None) -> None:
        self._tags_by_caption = tags_by_caption or {}

    def tag(self, caption: str) -> list[str]:
        if caption in self._tags_by_caption:
            return self._tags_by_caption[caption]
        first_word = caption.strip().split()[0].lower() if caption.strip() else "untagged"
        return [first_word]


class FakeCollectionAssigner:
    """Deterministic assigner. Returns the caller-supplied assignment for a
    caption; otherwise reuses the first known collection whose name appears in
    the caption, and falls back to a confident default collection (NOT
    UNCATEGORIZED — tests that want to exercise the "assigner is unsure, ask
    the user" path must opt in explicitly via `assignments`, since UNCATEGORIZED
    is treated by `Vault` as "pause and ask", not a normal answer). Records the
    `known` taxonomy it was handed so tests can assert it is actually offered
    existing options."""

    def __init__(
        self,
        assignments: dict[str, CollectionAssignment] | None = None,
        default_collection: str = "General",
    ) -> None:
        self._assignments = assignments or {}
        self._default_collection = default_collection
        self.seen_known: list[dict[str, list[str]]] = []

    def assign(self, caption: str, known: dict[str, list[str]]) -> CollectionAssignment:
        self.seen_known.append(known)
        if caption in self._assignments:
            return self._assignments[caption]

        lowered = caption.lower()
        for collection in known:
            if collection.lower() in lowered:
                return CollectionAssignment(collection=collection)
        return CollectionAssignment(collection=self._default_collection)


class FakeThumbnailStore:
    """Hands back a stable made-up reference for any URL, recording what it
    was asked to store. `fail=True` simulates an upload that blows up."""

    def __init__(self, fail: bool = False) -> None:
        self._fail = fail
        self.calls: list[str] = []

    def store(self, thumbnail_url: str) -> str | None:
        if self._fail:
            raise RuntimeError("upload failed")
        self.calls.append(thumbnail_url)
        return f"file-id-for:{thumbnail_url}"


class FakeEmbedder:
    """Deterministic bag-of-words embedding: cosine similarity between two
    texts reflects shared-word overlap, which is enough to exercise search
    ranking/thresholding without a real model.

    Uses crc32 rather than the builtin `hash`, which is salted per process
    (PYTHONHASHSEED) and would make word->dimension mapping — and therefore
    every similarity score — differ between runs.
    """

    def __init__(self, dim: int = 256) -> None:
        self._dim = dim
        self.calls: list[str] = []

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        vec = [0.0] * self._dim
        for word in text.lower().split():
            vec[zlib.crc32(word.encode()) % self._dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class InMemoryReelStore:
    def __init__(self) -> None:
        self._by_url: dict[str, SavedReel] = {}
        self.search_calls: list[int] = []

    def find_by_url(self, normalized_url: str) -> SavedReel | None:
        return self._by_url.get(normalized_url)

    def save(self, reel: SavedReel) -> None:
        self._by_url[normalize_reel_url(reel.url)] = reel

    def known_collections(self) -> dict[str, list[str]]:
        known: dict[str, list[str]] = {}
        for reel in self._by_url.values():
            subs = known.setdefault(reel.collection, [])
            if reel.subcollection and reel.subcollection not in subs:
                subs.append(reel.subcollection)
        return known

    def find_by_author(self, name: str) -> list[SavedReel]:
        wanted = name.casefold().lstrip("@")
        return [
            reel
            for reel in self._by_url.values()
            if wanted in {
                (reel.author_handle or "").casefold(),
                (reel.author_name or "").casefold(),
            }
        ]

    def search(
        self, query_embedding: list[float], top_k: int
    ) -> list[tuple[SavedReel, float]]:
        self.search_calls.append(top_k)
        scored = [
            (reel, _cosine(query_embedding, reel.embedding))
            for reel in self._by_url.values()
        ]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:top_k]


class FakeQueryIntent:
    """Keyword-driven stand-in for the LLM classifier. Checks in priority
    order — an @handle means an author filter, then browse phrasing, then
    aggregate phrasing — because real queries overlap ('show me all my X
    reels' browses; 'give me all the X from my Y' synthesizes)."""

    def __init__(
        self,
        aggregate_triggers: tuple[str, ...] = ("give me all", "summarize", "every"),
        list_triggers: tuple[str, ...] = ("show me", "list ", "browse"),
        classifications: Mapping[str, QueryClassification] | None = None,
    ) -> None:
        self._aggregate_triggers = aggregate_triggers
        self._list_triggers = list_triggers
        self._classifications = classifications or {}

    def classify(self, query: str) -> QueryClassification:
        if query in self._classifications:
            return self._classifications[query]

        lowered = query.lower()

        handle = re.search(r"@([\w.]+(?: [A-Z][\w.]*)*)", query)
        if handle:
            return QueryClassification(
                kind=QueryKind.AUTHOR_FILTER, author=handle.group(1)
            )
        if any(trigger in lowered for trigger in self._list_triggers):
            return QueryClassification(kind=QueryKind.LIST)
        if any(trigger in lowered for trigger in self._aggregate_triggers):
            return QueryClassification(kind=QueryKind.AGGREGATE)
        return QueryClassification(kind=QueryKind.SINGLE)


class FakeSummarizer:
    """Records what it was asked to summarize, so tests can assert both that
    a list query never reaches it and that aggregate queries hand it the
    right captions and authors. Echoes the attribution it was given, so a
    test can tell whether author actually reached the summarizer."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[SummarySource]]] = []

    def summarize(self, query: str, sources: list[SummarySource]) -> str:
        self.calls.append((query, list(sources)))
        return " | ".join(
            f"{source.caption} (by {source.author_handle or 'unknown'})"
            for source in sources
        )


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a)) or 1.0
    norm_b = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (norm_a * norm_b)
