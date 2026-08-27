"""The vault's core seam: `save_reel` and `ask`.

All environment-dependent behavior (Instagram fetching, tagging, embedding,
persistence, query-intent classification, summarization) is injected as
adapters conforming to `reel_vault.ports`. This module has no knowledge of
Telegram, Groq, Postgres, or any other concrete integration.
"""

from __future__ import annotations

import logging

from reel_vault.models import (
    UNCATEGORIZED,
    AggregateAnswer,
    AlreadySaved,
    Answer,
    ExtractedPost,
    ExtractionFailed,
    ListAnswer,
    NeedsCollectionChoice,
    NoMatch,
    QueryKind,
    Saved,
    SavedReel,
    SaveResult,
    SingleItemAnswer,
    SummarySource,
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

logger = logging.getLogger(__name__)

DEFAULT_MATCH_THRESHOLD = 0.35

# One cap per intent, not one shared cap: a list costs only a database read, so
# it can be generous, while every reel in an aggregate becomes part of a single
# LLM prompt — the free-tier budget, not relevance, is what bounds it.
DEFAULT_TOP_K_SINGLE = 5
DEFAULT_TOP_K_LIST = 50
DEFAULT_TOP_K_AGGREGATE = 15


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
        top_k_single: int = DEFAULT_TOP_K_SINGLE,
        top_k_list: int = DEFAULT_TOP_K_LIST,
        top_k_aggregate: int = DEFAULT_TOP_K_AGGREGATE,
    ) -> None:
        self._caption_fetcher = caption_fetcher
        self._tagger = tagger
        self._collection_assigner = collection_assigner
        self._embedder = embedder
        self._store = store
        self._query_intent = query_intent
        self._summarizer = summarizer
        self._match_threshold = match_threshold
        self._top_k = {
            QueryKind.SINGLE: top_k_single,
            QueryKind.LIST: top_k_list,
            QueryKind.AGGREGATE: top_k_aggregate,
            # Author queries are a plain filter, not a similarity search, so
            # this bounds the rows handed back rather than the search itself.
            QueryKind.AUTHOR_FILTER: top_k_list,
        }

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
        # call never needs to re-tag, re-embed, or re-upload the thumbnail.
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
                thumbnail_url=post.thumbnail_url,
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
        return Saved(reel=reel, thumbnail_url=post.thumbnail_url)

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
        return Saved(reel=reel, thumbnail_url=pending.thumbnail_url)

    def attach_thumbnail(self, url: str, thumbnail_ref: str) -> None:
        """Record a durable reference to a saved reel's picture. Only the
        transport layer can mint one, so it is supplied after the save rather
        than fetched during it."""
        self._store.set_thumbnail_ref(normalize_reel_url(url), thumbnail_ref)

    def ask(self, query: str) -> Answer:
        classification = self._query_intent.classify(query)
        kind = classification.kind

        if kind is QueryKind.AUTHOR_FILTER and classification.author:
            found = self._store.find_by_author(classification.author)
            return ListAnswer(
                query=query,
                reels=found[: self._top_k[kind]],
                author=classification.author,
            )

        query_embedding = self._embedder.embed(query)
        matches = [
            reel
            for reel, similarity in self._store.search(query_embedding, self._top_k[kind])
            if similarity >= self._match_threshold
        ]

        if not matches:
            return NoMatch(query=query)

        if kind is QueryKind.AGGREGATE:
            sources = [SummarySource.of(reel) for reel in matches]
            return AggregateAnswer(
                text=self._summarizer.summarize(query, sources), reels=matches
            )

        # An AUTHOR_FILTER reaching here named nobody the classifier could
        # pin down, so the semantic path is the better of the two guesses.
        if kind in (QueryKind.LIST, QueryKind.AUTHOR_FILTER):
            return ListAnswer(query=query, reels=matches)

        return SingleItemAnswer(reel=matches[0])
