"""Domain types for the vault's core seam (`save_reel`, `ask`)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

UNCATEGORIZED = "Uncategorized"


class ProcessingStatus(Enum):
    """Where a reel stands in the media pipeline (download → transcribe →
    analyse frames).

    The pipeline runs in the bot process and keeps nothing of its own, so a
    restart mid-job would otherwise lose that work silently — a reel missing
    its transcript looks exactly like a reel that never had one, and nobody
    finds out until an answer is quietly worse for it. This column is the
    whole durability mechanism: anything still PENDING at startup is picked
    up again.
    """

    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"
    # Reels saved before the pipeline existed. Distinct from DONE, which
    # claims the video was actually read, and from PENDING, which would queue
    # every old reel for download the next time the bot starts.
    SKIPPED = "skipped"


@dataclass(frozen=True)
class MediaExtraction:
    """What a `MediaExtractor` recovers from a reel's video: the words spoken
    in it, and what was shown on screen. Both are raw — condensing them is a
    separate, swappable step, so that a summary judged poor later can be
    remade from text the vault still holds rather than by re-downloading a
    video whose URL may be long gone."""

    transcript: str = ""
    frame_analysis: str = ""

    def is_empty(self) -> bool:
        return not self.transcript.strip() and not self.frame_analysis.strip()


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
    # What the video said and showed, kept twice over. The `_raw` halves are
    # never embedded and never searched: they exist so a summary that turns
    # out to be poor can be redone from the words themselves, instead of
    # re-downloading a video whose source URL expires. The `_summary` halves
    # are what retrieval and answers actually read.
    transcript_raw: str = ""
    transcript_summary: str = ""
    frame_analysis_raw: str = ""
    frame_analysis_summary: str = ""
    processing_status: ProcessingStatus = ProcessingStatus.PENDING
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
    """One matched reel as an answer-writer sees it. Deliberately narrower
    than `SavedReel` — the words and who wrote them, not the embedding — and
    deliberately includes the author, without which no "which creator said
    what" question can be answered at all.

    `transcript` and `frame_text` are the condensed halves, never the raw
    ones: a full transcript per reel would blow a multi-reel prompt's budget
    on the reels nobody asked about. They are separate fields rather than
    folded into `caption` so a prompt can say where a claim came from — a
    creator's own written caption is a different kind of evidence from a
    machine's reading of their video.
    """

    caption: str
    author_handle: str | None = None
    author_name: str | None = None
    transcript: str = ""
    frame_text: str = ""

    @classmethod
    def of(cls, reel: SavedReel) -> SummarySource:
        return cls(
            caption=reel.caption,
            author_handle=reel.author_handle,
            author_name=reel.author_name,
            transcript=reel.transcript_summary,
            frame_text=reel.frame_analysis_summary,
        )


class QueryKind(Enum):
    """What shape of answer a query is asking for. Chosen by `QueryIntent`
    in a single classification call — never by the user picking a mode."""

    SINGLE = "single"
    LIST = "list"
    AGGREGATE = "aggregate"
    AUTHOR_FILTER = "author_filter"
    # Both of these live inside what "aggregate" used to mean, and are pulled
    # out because they are different jobs, not different phrasings of one.
    # Ranking has to pick a winner and say by what measure; compiling has to
    # pull one specific thing out of many reels and merge the duplicates. A
    # single broadly-scoped prompt left to work out its own answer shape is
    # what produced the summarizer hallucination already on record, so each
    # gets told precisely what it is for instead.
    COMPARE_RANK = "compare_rank"
    EXTRACT_COMPILE = "extract_compile"


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
class Comparison:
    """A ranked answer and the measure it was ranked by, as the comparer
    produced them. The criterion travels with the text rather than being
    buried inside it so the caller can be sure it was stated at all."""

    text: str
    criterion: str


@dataclass(frozen=True)
class CompareAnswer:
    """One thing picked out of many, and the measure that picked it.

    `criterion` is its own field because "best" almost never means one
    obvious thing — best bicep workout could be most effective, quickest, or
    least equipment — and an answer that hides which one it used cannot be
    disagreed with. Stating it is what lets the user re-ask, and is why this
    is not a clarifying question back: `ask` stays one stateless call."""

    text: str
    criterion: str
    reels: list[SavedReel]


@dataclass(frozen=True)
class ExtractAnswer:
    """The things asked for, pulled out of many reels and merged.

    A list, not prose: someone asking for "all the interview questions across
    my reels" wants the questions, and a paragraph describing them is work
    handed back to the reader. Deliberately its own type rather than an
    `AggregateAnswer` whose `text` happens to contain bullets, for the same
    reason `ListAnswer` is: a shared shape with a sometimes-different meaning
    is an invariant every caller has to remember."""

    items: list[str]
    reels: list[SavedReel]


@dataclass(frozen=True)
class NoMatch:
    query: str


Answer = (
    SingleItemAnswer
    | ListAnswer
    | AggregateAnswer
    | CompareAnswer
    | ExtractAnswer
    | NoMatch
)
