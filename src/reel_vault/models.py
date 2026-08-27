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
    collection: str = UNCATEGORIZED
    subcollection: str | None = None
    author_handle: str | None = None
    author_name: str | None = None
    # A reference we control and that does not expire — not the extracted
    # CDN URL, which is signed and eventually 404s.
    thumbnail_ref: str | None = None
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
    own. Everything already computed (caption, tags, embedding, author) is
    carried here so finishing the save via `Vault.assign_collection` never
    needs to re-fetch, re-tag, or re-embed."""

    url: str
    caption: str
    tags: list[str]
    embedding: list[float]
    author_handle: str | None
    author_name: str | None
    known_collections: dict[str, list[str]]
    thumbnail_url: str | None = None


SaveResult = Saved | AlreadySaved | ExtractionFailed | NeedsCollectionChoice


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
    named. Extracted in the same call as `kind` so classification never costs
    a second LLM round-trip."""

    kind: QueryKind
    author: str | None = None


@dataclass(frozen=True)
class SingleItemAnswer:
    reel: SavedReel


@dataclass(frozen=True)
class ListAnswer:
    """Matched reels handed back as-is, for browsing. Deliberately a distinct
    type rather than an `AggregateAnswer` with empty `text`, so that
    `AggregateAnswer.text` is always a real synthesized answer.

    `author` is set when the list came from an author filter rather than a
    topic search — an empty `reels` then means "that creator, nothing saved",
    which is a different statement from "nothing matched your topic"."""

    query: str
    reels: list[SavedReel]
    author: str | None = None


@dataclass(frozen=True)
class AggregateAnswer:
    text: str
    reels: list[SavedReel]


@dataclass(frozen=True)
class NoMatch:
    query: str


Answer = SingleItemAnswer | ListAnswer | AggregateAnswer | NoMatch
