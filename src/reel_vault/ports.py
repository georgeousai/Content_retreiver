"""Adapter protocols the vault depends on. Environment-specific implementations
(Instagram fetching, Groq, sentence-transformers, Postgres/pgvector, ...) live
under `reel_vault.adapters` and are injected into `Vault`, never imported by it.
"""

from __future__ import annotations

from typing import Protocol

from reel_vault.models import CollectionAssignment, ExtractedPost, SavedReel


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

    def save(self, reel: SavedReel) -> None:
        ...

    def known_collections(self) -> dict[str, list[str]]:
        """Every collection currently in the vault, mapped to its
        sub-collections. Feeds the `CollectionAssigner`."""
        ...

    def search(
        self, query_embedding: list[float], top_k: int
    ) -> list[tuple[SavedReel, float]]:
        """Return up to `top_k` (reel, cosine_similarity) pairs, best match first."""
        ...


class QueryIntent(Protocol):
    def is_aggregate(self, query: str) -> bool:
        """True if the query asks for a synthesized answer across many reels
        rather than a single matching reel."""
        ...


class Summarizer(Protocol):
    def summarize(self, query: str, captions: list[str]) -> str:
        ...
