"""Domain types for the vault's core seam (`save_reel`, `ask`)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class SavedReel:
    url: str
    caption: str
    tags: list[str]
    embedding: list[float]
    saved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class Saved:
    """A new `SavedReel` was created."""

    reel: SavedReel


@dataclass(frozen=True)
class AlreadySaved:
    """The URL was already in the vault; no new row was created."""

    reel: SavedReel


@dataclass(frozen=True)
class ExtractionFailed:
    """Neither oEmbed nor the scraper fallback produced a usable caption."""

    url: str


SaveResult = Saved | AlreadySaved | ExtractionFailed


@dataclass(frozen=True)
class SingleItemAnswer:
    reel: SavedReel


@dataclass(frozen=True)
class AggregateAnswer:
    text: str
    reels: list[SavedReel]


@dataclass(frozen=True)
class NoMatch:
    query: str


Answer = SingleItemAnswer | AggregateAnswer | NoMatch
