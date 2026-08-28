"""Domain types for the vault's core seam (`save_reel`, `ask`)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

UNCATEGORIZED = "Uncategorized"


@dataclass(frozen=True)
class ExtractedPost:
    """What a `CaptionFetcher` recovers from a URL. Author and thumbnail fields
    are optional because not every extraction route exposes them (oEmbed,
    manual paste)."""

    caption: str
    author_handle: str | None = None
    author_name: str | None = None
    thumbnail_url: str | None = None


@dataclass(frozen=True)
class CollectionAssignment:
    """Where a reel belongs in the browsing taxonomy: exactly one collection,
    plus an optional finer-grained sub-collection."""

    collection: str
    subcollection: str | None = None


@dataclass(frozen=True)
class SavedReel:
    url: str
    caption: str
    tags: list[str]
    embedding: list[float]
    # The caption on its own, kept alongside the retrieval embedding above
    # (which also covers the collection and tags). Asking "where did reels
    # like this one go?" has to compare captions to captions: measuring a new
    # caption against embeddings that already contain shelf names would let a
    # collection pull in reels merely for sharing its vocabulary, which is
    # the reuse bias this lookup exists to counter.
    caption_embedding: list[float] = field(default_factory=list)
    collection: str = UNCATEGORIZED
    subcollection: str | None = None
    author_handle: str | None = None
    author_name: str | None = None
    # A reference we control and that does not expire — not the extracted
    # CDN URL, which is signed and eventually 404s.
    thumbnail_ref: str | None = None
    # Whether a person put this reel here, rather than the classifier. A
    # human placement is better evidence of where a library wants things than
    # a machine one, and is weighted accordingly when placing later reels.
    user_placed: bool = False
    saved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class Saved:
    """A new `SavedReel` was created.

    `thumbnail_url` is the extracted (expiring) image URL, passed out rather
    than stored: only the transport layer can turn it into a durable
    reference, and it hands that back via `Vault.attach_thumbnail`."""

    reel: SavedReel
    thumbnail_url: str | None = None


@dataclass(frozen=True)
class AlreadySaved:
    """The URL was already in the vault; no new row was created."""

    reel: SavedReel


@dataclass(frozen=True)
class ExtractionFailed:
    """Neither oEmbed nor the scraper fallback produced a usable caption."""

    url: str


@dataclass(frozen=True)
class NeedsCollectionChoice:
    """The collection assigner wasn't confident enough to pick one on its
    own. What was already computed (caption, tags, author) is carried here so
    finishing the save via `Vault.assign_collection` never needs to re-fetch
    or re-tag.

    The embedding is deliberately not among them. A reel is embedded together
    with the collection it is filed under, and that is the one thing this
    result does not yet know — carrying an embedding computed without it
    would file the reel under one name and make it findable by another."""

    url: str
    caption: str
    tags: list[str]
    # Carried, unlike the retrieval embedding, because it depends only on the
    # caption — the answer the user is about to give cannot change it.
    caption_embedding: list[float]
    author_handle: str | None
    author_name: str | None
    known_collections: dict[str, list[str]]
    thumbnail_url: str | None = None


SaveResult = Saved | AlreadySaved | ExtractionFailed | NeedsCollectionChoice


@dataclass(frozen=True)
class Correction:
    """One move of a reel from one shelf to another, as the user made it.

    Kept so a move can be undone. `from_user_placed` is part of the record
    because undoing has to restore not just where the reel sat but whether a
    person had put it there — otherwise reversing a move would leave behind a
    placement claiming human authority nobody exercised.
    """

    url: str
    from_collection: str
    from_subcollection: str | None
    to_collection: str
    to_subcollection: str | None
    from_user_placed: bool = False
    corrected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class NeighbourPlacement:
    """An already-filed reel whose caption resembles one being filed now, and
    where it ended up. Shown to the `CollectionAssigner` as evidence of how
    this particular library is organized, which the collection names alone
    cannot convey."""

    caption: str
    collection: str
    subcollection: str | None
    similarity: float
    user_placed: bool = False


@dataclass(frozen=True)
class SummarySource:
    """One matched reel as the summarizer sees it. Deliberately narrower than
    `SavedReel` — a summarizer needs the words and who wrote them, not the
    embedding — and deliberately includes the author, without which no
    "which creator said what" question can be answered at all."""

    caption: str
    author_handle: str | None = None
    author_name: str | None = None

    @classmethod
    def of(cls, reel: SavedReel) -> SummarySource:
        return cls(
            caption=reel.caption,
            author_handle=reel.author_handle,
            author_name=reel.author_name,
        )


class QueryKind(Enum):
    """What shape of answer a query is asking for. Chosen by `QueryIntent`
    in a single classification call — never by the user picking a mode."""

    SINGLE = "single"
    LIST = "list"
    AGGREGATE = "aggregate"
    AUTHOR_FILTER = "author_filter"


@dataclass(frozen=True)
class QueryClassification:
    """`author` is populated only for AUTHOR_FILTER — the creator the user
    named. `collection` is set whenever the query names one of the vault's
    existing collections ("my Sales reels"), which scopes retrieval to that
    shelf instead of guessing at it by similarity. Both are extracted in the
    same call as `kind`, so classification never costs a second LLM
    round-trip."""

    kind: QueryKind
    author: str | None = None
    collection: str | None = None


@dataclass(frozen=True)
class SingleItemAnswer:
    reel: SavedReel


@dataclass(frozen=True)
class ListAnswer:
    """Matched reels handed back as-is, for browsing. Deliberately a distinct
    type rather than an `AggregateAnswer` with empty `text`, so that
    `AggregateAnswer.text` is always a real synthesized answer.

    `author` and `collection` record what scoped the list, when something
    did. An empty `reels` alongside one of them means "that creator/shelf,
    nothing on it" — a different statement from "nothing matched your
    topic"."""

    query: str
    reels: list[SavedReel]
    author: str | None = None
    collection: str | None = None


@dataclass(frozen=True)
class AggregateAnswer:
    text: str
    reels: list[SavedReel]


@dataclass(frozen=True)
class NoMatch:
    query: str


Answer = SingleItemAnswer | ListAnswer | AggregateAnswer | NoMatch
