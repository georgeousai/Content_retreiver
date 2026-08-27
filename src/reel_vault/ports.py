"""Adapter protocols the vault depends on. Environment-specific implementations
(Instagram fetching, Groq, sentence-transformers, Postgres/pgvector, ...) live
under `reel_vault.adapters` and are injected into `Vault`, never imported by it.
"""

from __future__ import annotations

from typing import Protocol

from reel_vault.models import SavedReel


class CaptionFetcher(Protocol):
    def fetch(self, url: str) -> str | None:
        """Return the reel's caption, or None if it could not be extracted."""
        ...


class Tagger(Protocol):
    def tag(self, caption: str) -> list[str]:
        """Return zero or more open-vocabulary topic tags for a caption."""
        ...


class Embedder(Protocol):
    def embed(self, text: str) -> list[float]:
        ...


class ReelStore(Protocol):
    def find_by_url(self, normalized_url: str) -> SavedReel | None:
        ...

    def save(self, reel: SavedReel) -> None:
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
