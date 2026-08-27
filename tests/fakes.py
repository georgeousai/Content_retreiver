"""Fake adapters for exercising `Vault` without any real network/LLM/DB calls,
per the spec's testing decisions (tests target the seam, not the adapters)."""

from __future__ import annotations

import math
import zlib

from reel_vault.models import (
    UNCATEGORIZED,
    CollectionAssignment,
    ExtractedPost,
    SavedReel,
)
from reel_vault.urls import normalize_reel_url


class FakeCaptionFetcher:
    """Maps URL -> ExtractedPost. A missing/None entry simulates extraction
    failure. Plain strings are accepted as a shorthand for a caption with no
    author attached."""

    def __init__(self, posts: dict[str, ExtractedPost | str | None]) -> None:
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
    the caption, and falls back to UNCATEGORIZED. Records the `known` taxonomy
    it was handed so tests can assert it is actually offered existing options."""

    def __init__(
        self, assignments: dict[str, CollectionAssignment] | None = None
    ) -> None:
        self._assignments = assignments or {}
        self.seen_known: list[dict[str, list[str]]] = []

    def assign(self, caption: str, known: dict[str, list[str]]) -> CollectionAssignment:
        self.seen_known.append(known)
        if caption in self._assignments:
            return self._assignments[caption]

        lowered = caption.lower()
        for collection in known:
            if collection.lower() in lowered:
                return CollectionAssignment(collection=collection)
        return CollectionAssignment(collection=UNCATEGORIZED)


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

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        for word in text.lower().split():
            vec[zlib.crc32(word.encode()) % self._dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class InMemoryReelStore:
    def __init__(self) -> None:
        self._by_url: dict[str, SavedReel] = {}

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

    def search(
        self, query_embedding: list[float], top_k: int
    ) -> list[tuple[SavedReel, float]]:
        scored = [
            (reel, _cosine(query_embedding, reel.embedding))
            for reel in self._by_url.values()
        ]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:top_k]


class FakeQueryIntent:
    """Aggregate iff the query contains any of a caller-supplied set of
    trigger phrases; defaults to keywords like 'all'/'summarize'."""

    def __init__(self, aggregate_triggers: tuple[str, ...] = ("all", "summarize", "every")) -> None:
        self._triggers = aggregate_triggers

    def is_aggregate(self, query: str) -> bool:
        lowered = query.lower()
        return any(trigger in lowered for trigger in self._triggers)


class FakeSummarizer:
    def summarize(self, query: str, captions: list[str]) -> str:
        return " | ".join(captions)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a)) or 1.0
    norm_b = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (norm_a * norm_b)
