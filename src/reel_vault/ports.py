"""Adapter protocols the vault depends on. Environment-specific implementations
(Instagram fetching, Groq, sentence-transformers, Postgres/pgvector, ...) live
under `reel_vault.adapters` and are injected into `Vault`, never imported by it.
"""

from __future__ import annotations

from typing import Protocol

from reel_vault.models import (
    CollectionAssignment,
    Comparison,
    Correction,
    ExtractedPost,
    MediaExtraction,
    NeighbourPlacement,
    QueryClassification,
    SavedReel,
    SummarySource,
)


class CaptionFetcher(Protocol):
    def fetch(self, url: str) -> ExtractedPost | None:
        """Return the post's caption and author, or None if not extractable."""
        ...


class MediaExtractor(Protocol):
    def extract(self, url: str) -> MediaExtraction | None:
        """Everything the reel's video itself carries: what is said in it, and
        what is shown on screen. None when nothing could be recovered.

        One port for the whole job rather than one per step, mirroring how
        `CaptionFetcher` already hides oEmbed-then-scraper behind a single
        call: downloading, transcribing and reading frames share a video file
        that must not outlive them, so splitting them across ports would push
        that file's lifetime out into the caller.

        Returns None rather than raising. A reel is already saved and usable
        by the time this runs; failing to read its video is a smaller loss
        than an exception escaping into a background task.
        """
        ...


class ContentCondenser(Protocol):
    def condense(self, text: str) -> str:
        """Compact a transcript or a frame reading down to what is worth
        retrieving on.

        The long version is kept too, so this is allowed to be lossy — but
        not free to invent. It runs unattended on every reel, and unlike a
        caption there is no short source text sitting in front of the user to
        catch it against, which makes a confident wrong summary here harder
        to notice than the one already on record.
        """
        ...


class Tagger(Protocol):
    def tag(self, caption: str) -> list[str]:
        """Return zero or more open-vocabulary topic tags for a caption."""
        ...


class CollectionAssigner(Protocol):
    def assign(
        self,
        caption: str,
        known: dict[str, list[str]],
        neighbours: list[NeighbourPlacement],
    ) -> CollectionAssignment:
        """Place a caption in the taxonomy.

        `known` maps each existing collection to its existing sub-collections,
        so implementations can reuse what is already there instead of coining
        near-duplicates. `neighbours` are the most similar captions already
        filed, with where each went — the names alone say what shelves exist
        but nothing about what actually goes on them, which is how a reel
        captioned "Five Year Journey #smallbusiness" was filed under a
        Journey sub-collection that had nothing to do with it.
        """
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

    def find_similar_captions(
        self, caption_embedding: list[float], limit: int
    ) -> list[NeighbourPlacement]:
        """The already-filed reels whose captions most resemble this one.

        Compared caption-to-caption rather than against the retrieval
        embedding, which also covers collection and tags and would therefore
        favour whichever shelf happens to share the caption's vocabulary.
        """
        ...

    def record_correction(self, correction: Correction) -> None:
        """Remember that the user moved a reel, so the move can be undone."""
        ...

    def pop_last_correction(self, normalized_url: str) -> Correction | None:
        """Take back the most recent move of this reel, removing it from the
        record. Removed rather than kept-and-reversed: after an undo the reel
        sits where it was originally put, and a lingering record would claim
        a person chose that."""
        ...

    def update(self, reel: SavedReel) -> None:
        """Overwrite an already-saved reel, keyed on its URL.

        Re-filing is not a taxonomy-only edit: a reel is embedded and indexed
        together with the collection it sits on, so moving it between shelves
        has to rewrite what it is findable by, not just what it is labelled.
        The same is true of media: a transcript that arrived after the save
        changes what the reel is findable by, so this writes the media
        columns and the embedding together rather than leaving a reel
        carrying words no query can reach.
        """
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

    def find_awaiting_media(self) -> list[SavedReel]:
        """Every reel whose video has not been read yet.

        The background pipeline holds its queue only in memory, so this is
        what a restart reads to find the work it dropped. Reels already read,
        already failed, or saved before the pipeline existed are not here —
        an old reel is not the same thing as an interrupted one.
        """
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
        author so the answer can attribute across creators — and, where the
        video has been read, what was said and shown in it as well as what
        the caption wrote."""
        ...


class Comparer(Protocol):
    def compare(self, query: str, sources: list[SummarySource]) -> Comparison:
        """Rank the matched reels against what the user asked for and pick a
        winner, naming the measure used.

        A sibling of `Summarizer` rather than a mode of it: the two produce
        different answers and need different instructions, and the failure
        already on record came from one prompt being left to work out its own
        shape. Naming the criterion is not optional — "best" is ambiguous
        often enough that an unstated measure is an answer the user cannot
        argue with.
        """
        ...


class ItemExtractor(Protocol):
    def extract_items(self, query: str, sources: list[SummarySource]) -> list[str]:
        """Pull the specific things the user asked for out of the matched
        reels, merged and deduplicated across them.

        Returns the items themselves, not prose about them: the whole point
        of the request is to be handed a list, and a paragraph would hand the
        assembling work back to the reader.
        """
        ...
