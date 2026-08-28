"""Adapter protocols the vault depends on. Environment-specific implementations
(Instagram fetching, Groq, sentence-transformers, Postgres/pgvector, ...) live
under `reel_vault.adapters` and are injected into `Vault`, never imported by it.
"""

from __future__ import annotations

from typing import Protocol

from reel_vault.models import (
    CollectionAssignment,
    ExtractedPost,
    QueryClassification,
    SavedReel,
    SummarySource,
)


class CaptionFetcher(Protocol):
    def fetch(self, url: str) -> ExtractedPost | None:
        """Return the post's caption and author, or None if not extractable."""
        ...


class Tagger(Protocol):
    def tag(self, caption: str) -> list[str]:
        """Return zero or more open-vocabulary topic tags for a caption."""
        ...


class CollectionAssigner(Protocol):
    def assign(
        self, caption: str, known: dict[str, list[str]]
    ) -> CollectionAssignment:
        """Place a caption in the taxonomy. `known` maps each existing
        collection to its existing sub-collections, so implementations can
        reuse what is already there instead of coining near-duplicates."""
        ...


class Embedder(Protocol):
    def embed(self, text: str) -> list[float]:
        ...


class ReelStore(Protocol):
    def find_by_url(self, normalized_url: str) -> SavedReel | None:
        ...

    def save(self, reel: SavedReel) -> bool:
        """Persist a new reel. Returns False if one with this URL already
        existed, so a racing caller can tell "I saved it" from "someone
        already had"."""
        ...

    def known_collections(self) -> dict[str, list[str]]:
        """Every collection currently in the vault, mapped to its
        sub-collections. Feeds the `CollectionAssigner`."""
        ...

    def set_thumbnail_ref(self, normalized_url: str, thumbnail_ref: str) -> None:
        """Attach a durable picture reference to an already-saved reel."""
        ...

    def find_by_author(self, name: str) -> list[SavedReel]:
        """Every reel by one creator, matched against handle or display name.
        A plain filter — no embedding, no ranking: "everything from X" is an
        identity question, not a similarity one."""
        ...

    def find_by_collection(self, collection: str) -> list[SavedReel]:
        """Every reel filed under one collection. Also a plain filter: the
        taxonomy was decided at save time, so browsing it is a lookup rather
        than a guess."""
        ...

    def search(
        self, query_embedding: list[float], terms: list[str], top_k: int
    ) -> list[tuple[SavedReel, float]]:
        """Return up to `top_k` (reel, relevance) pairs, best match first.

        Hybrid: `query_embedding` matches captions by meaning, `terms` match
        the curated metadata (collection, sub-collection, tags) by word, and
        the two rankings are merged. Neither arm alone was enough — a reel
        filed under "Interviews" was unreachable by a query about interviews
        because only captions were searched, while a reel whose caption is
        "5yrs ago this wasn't a thing" is unreachable by word.

        Scores from both arms share one 0-1 scale so the caller can apply a
        single relevance threshold; see `reel_vault.search`.
        """
        ...


class QueryIntent(Protocol):
    def classify(self, query: str, collections: list[str]) -> QueryClassification:
        """Decide what shape of answer the query wants — one reel, a browsable
        list, a synthesized answer across many, or everything by one author —
        plus who, and which existing collection the user named, if any.
        `collections` is what the vault actually holds, so "my Sales reels"
        can be recognized as naming a shelf rather than describing a topic.
        One call, so classification never costs two LLM round-trips."""
        ...


class Summarizer(Protocol):
    def summarize(self, query: str, sources: list[SummarySource]) -> str:
        """Synthesize an answer from the matched reels. Sources carry their
        author so the answer can attribute across creators — but only ever
        from what the captions themselves say."""
        ...
