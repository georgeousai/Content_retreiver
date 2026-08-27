"""The vault's core seam: `save_reel` and `ask`.

All environment-dependent behavior (Instagram fetching, tagging, embedding,
persistence, query-intent classification, summarization) is injected as
adapters conforming to `reel_vault.ports`. This module has no knowledge of
Telegram, Groq, Postgres, or any other concrete integration.
"""

from __future__ import annotations

from reel_vault.models import (
    AggregateAnswer,
    AlreadySaved,
    Answer,
    ExtractionFailed,
    NoMatch,
    Saved,
    SavedReel,
    SaveResult,
    SingleItemAnswer,
)
from reel_vault.ports import (
    CaptionFetcher,
    Embedder,
    QueryIntent,
    ReelStore,
    Summarizer,
    Tagger,
)
from reel_vault.urls import normalize_reel_url

DEFAULT_MATCH_THRESHOLD = 0.35
DEFAULT_TOP_K = 5


class Vault:
    def __init__(
        self,
        *,
        caption_fetcher: CaptionFetcher,
        tagger: Tagger,
        embedder: Embedder,
        store: ReelStore,
        query_intent: QueryIntent,
        summarizer: Summarizer,
        match_threshold: float = DEFAULT_MATCH_THRESHOLD,
        top_k: int = DEFAULT_TOP_K,
    ) -> None:
        self._caption_fetcher = caption_fetcher
        self._tagger = tagger
        self._embedder = embedder
        self._store = store
        self._query_intent = query_intent
        self._summarizer = summarizer
        self._match_threshold = match_threshold
        self._top_k = top_k

    def save_reel(self, url: str, *, manual_caption: str | None = None) -> SaveResult:
        normalized = normalize_reel_url(url)

        existing = self._store.find_by_url(normalized)
        if existing is not None:
            return AlreadySaved(reel=existing)

        caption = manual_caption if manual_caption is not None else self._caption_fetcher.fetch(url)
        if not caption or not caption.strip():
            return ExtractionFailed(url=url)

        tags = self._tagger.tag(caption)
        embedding = self._embedder.embed(caption)
        reel = SavedReel(
            url=normalized,
            caption=caption,
            tags=tags,
            embedding=embedding,
        )
        self._store.save(reel)
        return Saved(reel=reel)

    def ask(self, query: str) -> Answer:
        query_embedding = self._embedder.embed(query)
        matches = [
            reel
            for reel, similarity in self._store.search(query_embedding, self._top_k)
            if similarity >= self._match_threshold
        ]

        if not matches:
            return NoMatch(query=query)

        if self._query_intent.is_aggregate(query):
            text = self._summarizer.summarize(query, [reel.caption for reel in matches])
            return AggregateAnswer(text=text, reels=matches)

        return SingleItemAnswer(reel=matches[0])
