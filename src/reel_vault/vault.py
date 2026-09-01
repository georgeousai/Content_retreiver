"""The vault's core seam: `save_reel` and `ask`.

All environment-dependent behavior (Instagram fetching, tagging, embedding,
persistence, query-intent classification, summarization) is injected as
adapters conforming to `reel_vault.ports`. This module has no knowledge of
Telegram, any model provider, Postgres, or any other concrete integration.
"""

from __future__ import annotations

import logging
from dataclasses import replace

from reel_vault.models import (
    UNCATEGORIZED,
    AggregateAnswer,
    AlreadySaved,
    Answer,
    CompareAnswer,
    Correction,
    ExtractAnswer,
    ExtractedPost,
    ExtractionFailed,
    ListAnswer,
    MediaExtraction,
    NeedsCollectionChoice,
    NoMatch,
    ProcessingStatus,
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
    Comparer,
    ContentCondenser,
    Embedder,
    ItemExtractor,
    MediaExtractor,
    QueryIntent,
    ReelStore,
    Summarizer,
    Tagger,
)
from reel_vault.search import embedding_text, search_terms
from reel_vault.substance import has_substance
from reel_vault.urls import normalize_reel_url

logger = logging.getLogger(__name__)

DEFAULT_MATCH_THRESHOLD = 0.35

# One cap per intent, not one shared cap: a list costs only a database read, so
# it can be generous, while every reel in an aggregate becomes part of a single
# LLM prompt — the free-tier budget, not relevance, is what bounds it.
DEFAULT_TOP_K_SINGLE = 5
DEFAULT_TOP_K_LIST = 50
DEFAULT_TOP_K_AGGREGATE = 15

# How many already-filed reels are shown to the collection assigner as
# evidence. Enough to show a pattern, few enough that one loud neighbour
# cannot decide the answer on its own.
DEFAULT_NEIGHBOUR_COUNT = 5

# How alike two captions must be before one is worth citing as evidence
# about the other. Without a floor, a genuinely novel reel is handed five
# unrelated placements scoring 0.15-0.18 and told they are precedent —
# noise presented in the same shape as a real signal, which is worse than
# saying nothing.
DEFAULT_NEIGHBOUR_FLOOR = 0.25


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
        comparer: Comparer,
        item_extractor: ItemExtractor,
        condenser: ContentCondenser,
        # Optional because the vault is fully usable without it: a reel
        # answers on its caption alone, exactly as it did before this
        # pipeline existed, and every test that is not about media should not
        # have to supply one.
        media_extractor: MediaExtractor | None = None,
        match_threshold: float = DEFAULT_MATCH_THRESHOLD,
        top_k_single: int = DEFAULT_TOP_K_SINGLE,
        top_k_list: int = DEFAULT_TOP_K_LIST,
        top_k_aggregate: int = DEFAULT_TOP_K_AGGREGATE,
        neighbour_count: int = DEFAULT_NEIGHBOUR_COUNT,
        neighbour_floor: float = DEFAULT_NEIGHBOUR_FLOOR,
    ) -> None:
        self._caption_fetcher = caption_fetcher
        self._tagger = tagger
        self._collection_assigner = collection_assigner
        self._embedder = embedder
        self._store = store
        self._query_intent = query_intent
        self._summarizer = summarizer
        self._comparer = comparer
        self._item_extractor = item_extractor
        self._media_extractor = media_extractor
        self._condenser = condenser
        self._match_threshold = match_threshold
        self._neighbour_count = neighbour_count
        self._neighbour_floor = neighbour_floor
        self._top_k = {
            QueryKind.SINGLE: top_k_single,
            QueryKind.LIST: top_k_list,
            QueryKind.AGGREGATE: top_k_aggregate,
            # Author queries are a plain filter, not a similarity search, so
            # this bounds the rows handed back rather than the search itself.
            QueryKind.AUTHOR_FILTER: top_k_list,
            # Both read every match into one prompt, like AGGREGATE, so the
            # free-tier budget bounds them the same way.
            QueryKind.COMPARE_RANK: top_k_aggregate,
            QueryKind.EXTRACT_COMPILE: top_k_aggregate,
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
        # Where comparable reels actually ended up, which the list of
        # collection names cannot convey: names say what shelves exist, not
        # what goes on them.
        caption_embedding = self._embedder.embed(post.caption)
        neighbours = [
            neighbour
            for neighbour in self._store.find_similar_captions(
                caption_embedding, self._neighbour_count
            )
            if neighbour.similarity >= self._neighbour_floor
        ]
        assignment = self._collection_assigner.assign(post.caption, known, neighbours)

        if assignment.collection == UNCATEGORIZED:
            # Nothing is embedded yet: a reel is embedded together with the
            # collection it is filed under, and that is exactly what this
            # outcome is asking the user for.
            return NeedsCollectionChoice(
                url=normalized,
                caption=post.caption,
                tags=tags,
                caption_embedding=caption_embedding,
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
            caption_embedding=caption_embedding,
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
        caption_embedding: list[float] | None = None,
        user_placed: bool = False,
    ) -> SavedReel:
        """Assemble a reel with both of the embeddings it needs.

        The single place either is computed, so the text they cover cannot
        differ between a reel saved outright and one the user placed by hand.
        The retrieval embedding covers the caption plus the shelf and tags;
        the caption embedding covers only the caption, and is what later
        reels are compared against when deciding where they belong.
        """
        return SavedReel(
            url=url,
            caption=caption,
            tags=tags,
            embedding=self._embedder.embed(
                embedding_text(caption, tags, collection, subcollection)
            ),
            caption_embedding=(
                caption_embedding
                if caption_embedding is not None
                else self._embedder.embed(caption)
            ),
            collection=collection,
            subcollection=subcollection,
            author_handle=author_handle,
            author_name=author_name,
            user_placed=user_placed,
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
            caption_embedding=pending.caption_embedding,
            # The user answered the question themselves, so this placement
            # carries their authority when later reels are placed near it.
            user_placed=True,
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
            user_placed=True,
            embedding=self._embedder.embed(
                self._embedding_text_for(existing, collection, subcollection)
            ),
        )
        self._store.update(moved)
        self._store.record_correction(
            Correction(
                url=normalized,
                from_collection=existing.collection,
                from_subcollection=existing.subcollection,
                to_collection=collection,
                to_subcollection=subcollection,
                from_user_placed=existing.user_placed,
            )
        )
        return moved

    def undo_last_move(self, url: str) -> SavedReel | None:
        """Put a reel back where it was before the last move, or None if it
        has not been moved (or is not in the vault at all).

        The record of the move is removed rather than reversed: afterwards
        the reel sits where it was originally put, and a correction left
        standing would claim a person had chosen that. Restoring
        `user_placed` from the record matters for the same reason — undoing
        a move must not leave behind a placement carrying an authority
        nobody exercised.
        """
        normalized = normalize_reel_url(url)
        correction = self._store.pop_last_correction(normalized)
        if correction is None:
            return None

        existing = self._store.find_by_url(normalized)
        if existing is None:
            return None

        restored = replace(
            existing,
            collection=correction.from_collection,
            subcollection=correction.from_subcollection,
            user_placed=correction.from_user_placed,
            embedding=self._embedder.embed(
                self._embedding_text_for(
                    existing,
                    correction.from_collection,
                    correction.from_subcollection,
                )
            ),
        )
        self._store.update(restored)
        return restored

    def _embedding_text_for(
        self, reel: SavedReel, collection: str, subcollection: str | None
    ) -> str:
        """What an already-saved reel should be embedded as if it sat on a
        different shelf. Everything except the shelf comes from the reel, so
        a move cannot quietly drop the transcript a reel had already earned
        — which is exactly what re-deriving the text from the caption alone
        would do."""
        return embedding_text(
            reel.caption,
            reel.tags,
            collection,
            subcollection,
            reel.transcript_summary,
            reel.frame_analysis_summary,
        )

    def process_media(self, url: str) -> SavedReel | None:
        """Read the reel's video and record what it said and showed.

        Slow — a download, a transcription and a run of vision calls — so the
        caller runs it off the path that answers the user. It is the caller's
        job to do that, not this method's: the vault stays synchronous, and
        how work is got off the main thread is a property of the transport
        running it.

        Returns the updated reel, or None if the vault has no such reel or
        no extractor is configured.
        """
        if self._media_extractor is None:
            return None

        normalized = normalize_reel_url(url)
        if self._store.find_by_url(normalized) is None:
            return None

        try:
            extraction = self._media_extractor.extract(normalized)
        except Exception:
            # The reel is already saved and already answers on its caption.
            # A background job that takes the process down with it, or leaves
            # a reel wedged on PENDING forever, is the worse outcome.
            logger.exception("Media extraction raised for %s", normalized)
            extraction = None

        return self.attach_media(normalized, extraction)

    def attach_media(
        self, url: str, extraction: MediaExtraction | None
    ) -> SavedReel | None:
        """Record what a reel's video turned out to contain.

        The reel is re-embedded, not merely annotated. A reel is findable by
        the text it was embedded as, so a transcript written into a column
        the embedding never saw would be words the vault holds and no query
        can reach — the same trap that made a moved reel still findable under
        the shelf it had left.

        A failed extraction is recorded as failed rather than left pending.
        Retrying forever on a video that has expired would re-download it on
        every restart for as long as the reel exists.
        """
        normalized = normalize_reel_url(url)
        existing = self._store.find_by_url(normalized)
        if existing is None:
            return None

        if extraction is None or extraction.is_empty():
            failed = replace(existing, processing_status=ProcessingStatus.FAILED)
            self._store.update(failed)
            return failed

        try:
            transcript_summary = self._condense(extraction.transcript)
            frame_summary = self._condense(extraction.frame_analysis)
        except Exception:
            # Keep the words, drop the claim to have read them. The raw text
            # is exactly what condensing needs, so a later pass can finish
            # this reel without downloading the video again — which is the
            # whole reason both halves are stored. Falling back to embedding
            # the raw text instead would put a full transcript into the
            # embedding and drown out the caption and the shelf it sits on.
            logger.exception("Condensing failed for %s", normalized)
            kept = replace(
                existing,
                transcript_raw=extraction.transcript,
                frame_analysis_raw=extraction.frame_analysis,
                processing_status=ProcessingStatus.FAILED,
            )
            self._store.update(kept)
            return kept

        read = replace(
            existing,
            transcript_raw=extraction.transcript,
            transcript_summary=transcript_summary,
            frame_analysis_raw=extraction.frame_analysis,
            frame_analysis_summary=frame_summary,
            processing_status=ProcessingStatus.DONE,
        )
        # Embedded from the reel as it now is, through the same one function
        # a move uses. Spelling the parts out here instead would mean two
        # places had to learn about every future embedded field — the drift
        # that once let the URL matcher and the dedup key disagree.
        updated = replace(
            read,
            embedding=self._embedder.embed(
                self._embedding_text_for(read, read.collection, read.subcollection)
            ),
        )
        self._store.update(updated)
        return updated

    def _condense(self, raw: str) -> str:
        """The compact half of a piece of media text, and the only half that
        is ever embedded.

        Text with nothing in it never reaches the model. That is a cost
        saving rather than a correction — Whisper's `"."` on a silent clip is
        not a judgement call, and paying twice a reel to have one made is
        waste. Everything else is the condenser's own call, including whether
        a hook is worth keeping, which it makes correctly once it is able to
        answer at all: see `reel_vault.substance` and `adapters.llm`'s
        `TruncatedResponse` for why "able to answer" was the whole problem.
        """
        if not has_substance(raw):
            return ""
        return self._condenser.condense(raw)

    def resume_pending_media(self) -> list[str]:
        """The reels whose video was never read, for the caller to schedule.

        The pipeline's queue lives in the running process and nothing else,
        so an interrupted run leaves exactly this behind. Returning the work
        rather than doing it keeps the decision about concurrency and pacing
        with the transport, which is the only layer that knows what else it
        is trying to do at the time.
        """
        return [reel.url for reel in self._store.find_awaiting_media()]

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

        written = self._written_answer(query, kind, matches)
        if written is not None:
            return written

        # An AUTHOR_FILTER reaching here named nobody the classifier could
        # pin down, so the semantic path is the better of the two guesses.
        if kind in (QueryKind.LIST, QueryKind.AUTHOR_FILTER):
            return ListAnswer(query=query, reels=matches)

        return SingleItemAnswer(reel=matches[0])

    def _written_answer(
        self, query: str, kind: QueryKind, reels: list[SavedReel]
    ) -> Answer | None:
        """The three kinds that read the matched reels and write something,
        or None for the kinds that just hand the reels back.

        Each goes to its own adapter with its own instructions rather than
        one prompt deciding for itself what shape to write in. That
        distinction is the whole reason these are separate kinds: told only
        to "answer the question", a model asked for the best of something
        will write a summary of everything, and asked for a list will write
        prose about one.
        """
        sources = [SummarySource.of(reel) for reel in reels]

        if kind is QueryKind.AGGREGATE:
            return AggregateAnswer(
                text=self._summarizer.summarize(query, sources), reels=reels
            )

        if kind is QueryKind.COMPARE_RANK:
            comparison = self._comparer.compare(query, sources)
            return CompareAnswer(
                text=comparison.text, criterion=comparison.criterion, reels=reels
            )

        if kind is QueryKind.EXTRACT_COMPILE:
            return ExtractAnswer(
                items=self._item_extractor.extract_items(query, sources), reels=reels
            )

        return None

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

        written = self._written_answer(query, kind, reels)
        if written is not None:
            return written

        if kind is QueryKind.SINGLE:
            return SingleItemAnswer(reel=reels[0])

        return ListAnswer(query=query, reels=reels, collection=collection)
