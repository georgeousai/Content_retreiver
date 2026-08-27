"""The vault's core seam: `save_reel` and `ask`.

All environment-dependent behavior (Instagram fetching, tagging, embedding,
persistence, query-intent classification, summarization) is injected as
adapters conforming to `reel_vault.ports`. This module has no knowledge of
Telegram, Groq, Postgres, or any other concrete integration.
"""

from __future__ import annotations

from reel_vault.models import (
    UNCATEGORIZED,
    AggregateAnswer,
    AlreadySaved,
    Answer,
    ExtractedPost,
    ExtractionFailed,
    NeedsCollectionChoice,
    NoMatch,
    Saved,
    SavedReel,
    SaveResult,
    SingleItemAnswer,
)
from reel_vault.ports import (
    CaptionFetcher,
    CollectionAssigner,
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
        collection_assigner: CollectionAssigner,
        embedder: Embedder,
        store: ReelStore,
        query_intent: QueryIntent,
        summarizer: Summarizer,
        match_threshold: float = DEFAULT_MATCH_THRESHOLD,
        top_k: int = DEFAULT_TOP_K,
    ) -> None:
        self._caption_fetcher = caption_fetcher
        self._tagger = tagger
        self._collection_assigner = collection_assigner
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

        post = (
            ExtractedPost(caption=manual_caption)
            if manual_caption is not None
            else self._caption_fetcher.fetch(url)
        )
        if post is None or not post.caption.strip():
            return ExtractionFailed(url=url)

        tags = self._tagger.tag(post.caption)
        known = self._store.known_collections()
        assignment = self._collection_assigner.assign(post.caption, known)
        # Computed regardless of outcome so a follow-up `assign_collection`
        # call never needs to re-tag or re-embed.
        embedding = self._embedder.embed(post.caption)

        if assignment.collection == UNCATEGORIZED:
            return NeedsCollectionChoice(
                url=normalized,
                caption=post.caption,
                tags=tags,
                embedding=embedding,
                author_handle=post.author_handle,
                author_name=post.author_name,
                known_collections=known,
            )

        reel = SavedReel(
            url=normalized,
            caption=post.caption,
            tags=tags,
            embedding=embedding,
            collection=assignment.collection,
            subcollection=assignment.subcollection,
            author_handle=post.author_handle,
            author_name=post.author_name,
        )
        self._store.save(reel)
        return Saved(reel=reel)

    def assign_collection(
        self,
        pending: NeedsCollectionChoice,
        *,
        collection: str,
        subcollection: str | None = None,
    ) -> Saved:
        """Finish a save that `save_reel` paused on `NeedsCollectionChoice`,
        now that the caller (the bot, having asked the user) supplies where
        it belongs."""
        reel = SavedReel(
            url=pending.url,
            caption=pending.caption,
            tags=pending.tags,
            embedding=pending.embedding,
            collection=collection,
            subcollection=subcollection,
            author_handle=pending.author_handle,
            author_name=pending.author_name,
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
