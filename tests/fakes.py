"""Fake adapters for exercising `Vault` without any real network/LLM/DB calls,
per the spec's testing decisions (tests target the seam, not the adapters)."""

from __future__ import annotations

import math
import re
import zlib
from collections.abc import Mapping
from dataclasses import replace

from reel_vault.models import (
    CollectionAssignment,
    Comparison,
    Correction,
    ExtractedPost,
    MediaExtraction,
    NeighbourPlacement,
    ProcessingStatus,
    QueryClassification,
    QueryKind,
    SavedReel,
    SummarySource,
)
from reel_vault.search import keyword_score, merge_hits, metadata_text
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
        self.seen_neighbours: list[list[NeighbourPlacement]] = []

    def assign(
        self,
        caption: str,
        known: dict[str, list[str]],
        neighbours: list[NeighbourPlacement],
    ) -> CollectionAssignment:
        self.seen_known.append(known)
        self.seen_neighbours.append(neighbours)
        if caption in self._assignments:
            return self._assignments[caption]

        lowered = caption.lower()
        for collection in known:
            if collection.lower() in lowered:
                return CollectionAssignment(collection=collection)
        return CollectionAssignment(collection=self._default_collection)


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
        self._corrections: dict[str, list[Correction]] = {}
        self.search_calls: list[int] = []

    def find_by_url(self, normalized_url: str) -> SavedReel | None:
        return self._by_url.get(normalized_url)

    def save(self, reel: SavedReel) -> bool:
        key = normalize_reel_url(reel.url)
        if key in self._by_url:
            return False
        self._by_url[key] = reel
        return True

    def update(self, reel: SavedReel) -> None:
        if reel.url in self._by_url:
            self._by_url[reel.url] = reel

    def find_similar_captions(
        self, caption_embedding: list[float], limit: int
    ) -> list[NeighbourPlacement]:
        scored = [
            (reel, _cosine(caption_embedding, reel.caption_embedding))
            for reel in self._by_url.values()
            if reel.caption_embedding
        ]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return [
            NeighbourPlacement(
                caption=reel.caption,
                collection=reel.collection,
                subcollection=reel.subcollection,
                similarity=similarity,
                user_placed=reel.user_placed,
            )
            for reel, similarity in scored[:limit]
        ]

    def record_correction(self, correction: Correction) -> None:
        self._corrections.setdefault(correction.url, []).append(correction)

    def pop_last_correction(self, normalized_url: str) -> Correction | None:
        history = self._corrections.get(normalized_url)
        if not history:
            return None
        return history.pop()

    def known_collections(self) -> dict[str, list[str]]:
        known: dict[str, list[str]] = {}
        for reel in self._by_url.values():
            subs = known.setdefault(reel.collection, [])
            if reel.subcollection and reel.subcollection not in subs:
                subs.append(reel.subcollection)
        return known

    def set_thumbnail_ref(self, normalized_url: str, thumbnail_ref: str) -> None:
        reel = self._by_url.get(normalized_url)
        if reel is not None:
            self._by_url[normalized_url] = replace(reel, thumbnail_ref=thumbnail_ref)

    def find_awaiting_media(self) -> list[SavedReel]:
        return [
            reel
            for reel in self._by_url.values()
            if reel.processing_status is ProcessingStatus.PENDING
        ]

    def find_by_collection(self, collection: str) -> list[SavedReel]:
        return [
            reel
            for reel in self._by_url.values()
            if reel.collection.casefold() == collection.casefold()
        ]

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
        self, query_embedding: list[float], terms: list[str], top_k: int
    ) -> list[tuple[SavedReel, float]]:
        self.search_calls.append(top_k)
        scored = [
            (reel, _cosine(query_embedding, reel.embedding))
            for reel in self._by_url.values()
        ]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return merge_hits(scored[:top_k], self._keyword_hits(terms), top_k)

    def _keyword_hits(self, terms: list[str]) -> list[tuple[SavedReel, float]]:
        """The keyword arm, standing in for Postgres's english text search.
        `_stems_alike` is a deliberately crude substitute for real stemming —
        enough that "interview" reaches a sub-collection named "Interviews",
        which is the behaviour these tests are about."""
        hits = []
        for reel in self._by_url.values():
            words = set(
                metadata_text(reel.tags, reel.collection, reel.subcollection)
                .casefold()
                .split()
            )
            matched = sum(
                any(_stems_alike(term, word) for word in words) for term in terms
            )
            score = keyword_score(matched, len(terms))
            if score > 0:
                hits.append((reel, score))
        return hits


def _stems_alike(term: str, word: str) -> bool:
    """Whether a query term and a metadata word are the same word. The length
    floor keeps a prefix rule from making every short word match everything —
    without it "ai" would match "aim", "air", and "aircraft"."""
    if term == word:
        return True
    return (len(term) >= 4 and word.startswith(term)) or (
        len(word) >= 4 and term.startswith(word)
    )


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
        compare_triggers: tuple[str, ...] = ("best ", "which is better", "rank"),
        extract_triggers: tuple[str, ...] = ("compile", "full list of"),
    ) -> None:
        self._aggregate_triggers = aggregate_triggers
        self._list_triggers = list_triggers
        self._classifications = classifications or {}
        self._compare_triggers = compare_triggers
        self._extract_triggers = extract_triggers

    def classify(self, query: str, collections: list[str]) -> QueryClassification:
        if query in self._classifications:
            return self._classifications[query]

        lowered = query.lower()

        handle = re.search(r"@([\w.]+(?: [A-Z][\w.]*)*)", query)
        if handle:
            return QueryClassification(
                kind=QueryKind.AUTHOR_FILTER, author=handle.group(1)
            )

        # Naming an existing collection scopes the answer to that shelf,
        # whatever shape of answer was asked for.
        named = next(
            (name for name in collections if name.casefold() in lowered), None
        )
        # Checked before the broader aggregate/list phrasings, which a real
        # ranking or compiling request tends to contain as well ("give me the
        # full list of ...", "show me the best ...").
        if any(trigger in lowered for trigger in self._compare_triggers):
            return QueryClassification(kind=QueryKind.COMPARE_RANK, collection=named)
        if any(trigger in lowered for trigger in self._extract_triggers):
            return QueryClassification(
                kind=QueryKind.EXTRACT_COMPILE, collection=named
            )
        if any(trigger in lowered for trigger in self._list_triggers):
            return QueryClassification(kind=QueryKind.LIST, collection=named)
        if any(trigger in lowered for trigger in self._aggregate_triggers):
            return QueryClassification(kind=QueryKind.AGGREGATE, collection=named)
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


class FakeComparer:
    """Ranks by whichever source has the most text to go on, and says so.
    Deterministic, and records its calls so a test can check the summarizer
    was never the one asked."""

    def __init__(self, criterion: str = "amount said about it") -> None:
        self._criterion = criterion
        self.calls: list[tuple[str, list[SummarySource]]] = []

    def compare(self, query: str, sources: list[SummarySource]) -> Comparison:
        self.calls.append((query, list(sources)))
        best = max(sources, key=lambda source: len(_all_text(source)), default=None)
        winner = best.caption if best is not None else "nothing"
        return Comparison(
            text=f"Best for {query}: {winner}", criterion=self._criterion
        )


class FakeItemExtractor:
    """Splits every source's text on newlines into items, deduplicated across
    reels while preserving order — a crude stand-in for the real extraction,
    but enough to exercise that duplicates across reels collapse."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[SummarySource]]] = []

    def extract_items(self, query: str, sources: list[SummarySource]) -> list[str]:
        self.calls.append((query, list(sources)))
        items: dict[str, None] = {}
        for source in sources:
            for line in _all_text(source).splitlines():
                if line.strip():
                    items.setdefault(line.strip(), None)
        return list(items)


class FakeMediaExtractor:
    """Maps URL -> MediaExtraction. A missing entry means nothing could be
    recovered from the video; an entry that is an exception is raised, so a
    test can check a failing extractor does not escape into the caller."""

    def __init__(
        self, extractions: Mapping[str, MediaExtraction | Exception | None] | None = None
    ) -> None:
        self._extractions = extractions or {}
        self.calls: list[str] = []

    def extract(self, url: str) -> MediaExtraction | None:
        self.calls.append(url)
        found = self._extractions.get(url)
        if isinstance(found, Exception):
            raise found
        return found


class FakeCondenser:
    """Condenses by keeping the first line, which is enough to tell a summary
    apart from the raw text it came from."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def condense(self, text: str) -> str:
        self.calls.append(text)
        first = text.strip().splitlines()[0] if text.strip() else ""
        return f"summary of: {first}"


def _all_text(source: SummarySource) -> str:
    """Everything a source carries, caption and video alike — what an answer
    writer actually has to work from."""
    return "\n".join(
        part for part in (source.caption, source.transcript, source.frame_text) if part
    )


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a)) or 1.0
    norm_b = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (norm_a * norm_b)
