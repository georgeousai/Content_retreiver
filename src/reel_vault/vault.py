"""The vault's core seam: `save_reel` and `ask`.

All environment-dependent behavior (Instagram fetching, tagging, embedding,
persistence, query-intent classification, summarization) is injected as
adapters conforming to `reel_vault.ports`. This module has no knowledge of
Telegram, Groq, Postgres, or any other concrete integration.
"""

from __future__ import annotations

import logging
from dataclasses import replace

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
    QueryClassification,
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
from reel_vault.search import embedding_text, search_terms
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

        if assignment.collection == UNCATEGORIZED:
            # Nothing is embedded yet: a reel is embedded together with the
            # collection it is filed under, and that is exactly what this
            # outcome is asking the user for.
            return NeedsCollectionChoice(
                url=normalized,
                caption=post.caption,
                tags=tags,
                author_handle=post.author_handle,
                author_name=post.author_name,
                known_collections=known,
                thumbnail_url=post.thumbnail_url,
            )

        reel = self._build_reel(
            url=normalized,
            caption=post.caption,
            tags=tags,
            collection=assignment.collection,
            subcollection=assignment.subcollection,
            author_handle=post.author_handle,
            author_name=post.author_name,
        )
        return self._persist(reel, thumbnail_url=post.thumbnail_url)

    def _build_reel(
        self,
        *,
        url: str,
        caption: str,
        tags: list[str],
        collection: str,
        subcollection: str | None,
        author_handle: str | None,
        author_name: str | None,
    ) -> SavedReel:
        """Assemble a reel, embedding it the way it will later be searched.

        The single place a reel's embedding is computed, so that the text it
        covers — caption plus the shelf and tags it was filed under — cannot
        differ between a reel saved outright and one the user had to place by
        hand."""
        return SavedReel(
            url=url,
            caption=caption,
            tags=tags,
            embedding=self._embedder.embed(
                embedding_text(caption, tags, collection, subcollection)
            ),
            collection=collection,
            subcollection=subcollection,
            author_handle=author_handle,
            author_name=author_name,
        )

    def _persist(self, reel: SavedReel, *, thumbnail_url: str | None) -> SaveResult:
        """Write the reel, unless someone beat us to that URL between our
        duplicate check and now — two bot processes, a double-tap, or (later)
        two users on the same reel. Claiming "Saved!" for a write that did
        nothing is worse than being late to notice."""
        if not self._store.save(reel):
            existing = self._store.find_by_url(reel.url)
            return AlreadySaved(reel=existing if existing is not None else reel)
        return Saved(reel=reel, thumbnail_url=thumbnail_url)

    def assign_collection(
        self,
        pending: NeedsCollectionChoice,
        *,
        collection: str,
        subcollection: str | None = None,
    ) -> SaveResult:
        """Finish a save that `save_reel` paused on `NeedsCollectionChoice`,
        now that the caller (the bot, having asked the user) supplies where
        it belongs."""
        reel = self._build_reel(
            url=pending.url,
            caption=pending.caption,
            tags=pending.tags,
            collection=collection,
            subcollection=subcollection,
            author_handle=pending.author_handle,
            author_name=pending.author_name,
        )
        return self._persist(reel, thumbnail_url=pending.thumbnail_url)

    def collections(self) -> list[str]:
        """Every collection the vault holds, for offering the user a choice."""
        return sorted(self._store.known_collections())

    def refile(
        self, url: str, *, collection: str, subcollection: str | None = None
    ) -> SavedReel | None:
        """Move an already-saved reel to a different shelf, or None if the
        vault doesn't have it.

        Where a reel belongs is often genuinely ambiguous — a five-year
        journey building a small business is both Personal Growth and
        Entrepreneurship — so this exists because no classifier, however
        well prompted, can be right for a user who disagrees with it.

        The reel is re-embedded rather than relabelled: since a reel is
        embedded together with its collection, a move that only rewrote the
        taxonomy would leave it still findable under the shelf it just left.
        """
        normalized = normalize_reel_url(url)
        existing = self._store.find_by_url(normalized)
        if existing is None:
            return None

        moved = replace(
            existing,
            collection=collection,
            subcollection=subcollection,
            embedding=self._embedder.embed(
                embedding_text(
                    existing.caption, existing.tags, collection, subcollection
                )
            ),
        )
        self._store.update(moved)
        return moved

    def attach_thumbnail(self, url: str, thumbnail_ref: str) -> None:
        """Record a durable reference to a saved reel's picture. Only the
        transport layer can mint one, so it is supplied after the save rather
        than fetched during it."""
        self._store.set_thumbnail_ref(normalize_reel_url(url), thumbnail_ref)

    def ask(self, query: str) -> Answer:
        known = list(self._store.known_collections())
        classification = self._query_intent.classify(query, known)
        kind = classification.kind

        if kind is QueryKind.AUTHOR_FILTER and classification.author:
            found = self._store.find_by_author(classification.author)
            return ListAnswer(
                query=query,
                reels=found[: self._top_k[kind]],
                author=classification.author,
            )

        if classification.collection:
            return self._answer_from_collection(query, classification)

        matches = [
            reel
            for reel, relevance in self._store.search(
                self._embedder.embed(query), search_terms(query), self._top_k[kind]
            )
            if relevance >= self._match_threshold
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

    def _answer_from_collection(
        self, query: str, classification: QueryClassification
    ) -> Answer:
        """The user named a shelf, so read the shelf. Similarity ranking has
        nothing to add here and plenty to lose: "5yrs ago this wasn't a thing"
        genuinely belongs to Sales, but no query about sales will ever score
        close enough to a caption like that to clear the threshold."""
        collection = classification.collection or ""
        kind = classification.kind
        reels = self._store.find_by_collection(collection)[: self._top_k[kind]]

        if not reels:
            return NoMatch(query=query)

        if kind is QueryKind.AGGREGATE:
            sources = [SummarySource.of(reel) for reel in reels]
            return AggregateAnswer(
                text=self._summarizer.summarize(query, sources), reels=reels
            )

        if kind is QueryKind.SINGLE:
            return SingleItemAnswer(reel=reels[0])

        return ListAnswer(query=query, reels=reels, collection=collection)
