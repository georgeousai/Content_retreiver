"""Postgres/pgvector-backed `ReelStore`. One row per `SavedReel`."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import timezone

import psycopg
from pgvector import Vector
from pgvector.psycopg import register_vector

from reel_vault.models import UNCATEGORIZED, SavedReel

SCHEMA = f"""
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS saved_reels (
    normalized_url TEXT PRIMARY KEY,
    caption TEXT NOT NULL,
    tags TEXT[] NOT NULL DEFAULT '{{}}',
    embedding VECTOR(384) NOT NULL,
    saved_at TIMESTAMPTZ NOT NULL
);

-- Added after the first release; ALTERs keep existing vaults working.
ALTER TABLE saved_reels
    ADD COLUMN IF NOT EXISTS collection TEXT NOT NULL DEFAULT '{UNCATEGORIZED}',
    ADD COLUMN IF NOT EXISTS subcollection TEXT,
    ADD COLUMN IF NOT EXISTS author_handle TEXT,
    ADD COLUMN IF NOT EXISTS author_name TEXT,
    ADD COLUMN IF NOT EXISTS thumbnail_ref TEXT;

CREATE INDEX IF NOT EXISTS saved_reels_collection_idx
    ON saved_reels (collection, subcollection);
CREATE INDEX IF NOT EXISTS saved_reels_author_idx ON saved_reels (author_handle);
"""

COLUMNS = (
    "normalized_url, caption, tags, embedding, collection, subcollection, "
    "author_handle, author_name, thumbnail_ref, saved_at"
)


class PostgresReelStore:
    def __init__(self, dsn: str) -> None:
        self._conn = psycopg.connect(dsn, autocommit=True)
        register_vector(self._conn)
        self._conn.execute(SCHEMA)

    def find_by_url(self, normalized_url: str) -> SavedReel | None:
        row = self._conn.execute(
            f"SELECT {COLUMNS} FROM saved_reels WHERE normalized_url = %s",
            (normalized_url,),
        ).fetchone()
        return _to_reel(row) if row else None

    def save(self, reel: SavedReel) -> None:
        self._conn.execute(
            f"INSERT INTO saved_reels ({COLUMNS}) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (normalized_url) DO NOTHING",
            (
                reel.url,
                reel.caption,
                reel.tags,
                Vector(reel.embedding),
                reel.collection,
                reel.subcollection,
                reel.author_handle,
                reel.author_name,
                reel.thumbnail_ref,
                reel.saved_at,
            ),
        )

    def known_collections(self) -> dict[str, list[str]]:
        rows = self._conn.execute(
            "SELECT collection, subcollection FROM saved_reels "
            "GROUP BY collection, subcollection ORDER BY collection, subcollection"
        ).fetchall()

        known: dict[str, list[str]] = {}
        for collection, subcollection in rows:
            subs = known.setdefault(collection, [])
            if subcollection and subcollection not in subs:
                subs.append(subcollection)
        return known

    def set_thumbnail_ref(self, normalized_url: str, thumbnail_ref: str) -> None:
        self._conn.execute(
            "UPDATE saved_reels SET thumbnail_ref = %s WHERE normalized_url = %s",
            (thumbnail_ref, normalized_url),
        )

    def find_by_author(self, name: str) -> list[SavedReel]:
        wanted = name.lstrip("@")
        rows = self._conn.execute(
            f"SELECT {COLUMNS} FROM saved_reels "
            "WHERE lower(author_handle) = lower(%s) OR lower(author_name) = lower(%s) "
            "ORDER BY saved_at DESC",
            (wanted, wanted),
        ).fetchall()
        return [_to_reel(row) for row in rows]

    def search(
        self, query_embedding: list[float], top_k: int
    ) -> list[tuple[SavedReel, float]]:
        # `Vector` is required so the parameter is sent as pgvector's `vector`
        # type; a bare list adapts to `double precision[]`, which has no `<=>`
        # operator.
        vector = Vector(query_embedding)
        rows = self._conn.execute(
            f"SELECT {COLUMNS}, 1 - (embedding <=> %s) AS similarity "
            "FROM saved_reels ORDER BY embedding <=> %s LIMIT %s",
            (vector, vector, top_k),
        ).fetchall()
        return [(_to_reel(row[:-1]), row[-1]) for row in rows]


def _to_reel(row: tuple) -> SavedReel:
    (
        normalized_url,
        caption,
        tags,
        embedding,
        collection,
        subcollection,
        author_handle,
        author_name,
        thumbnail_ref,
        saved_at,
    ) = row
    saved_at = saved_at if saved_at.tzinfo else saved_at.replace(tzinfo=timezone.utc)
    return SavedReel(
        url=normalized_url,
        caption=caption,
        tags=list(tags),
        embedding=_to_float_list(embedding),
        collection=collection,
        subcollection=subcollection,
        author_handle=author_handle,
        author_name=author_name,
        thumbnail_ref=thumbnail_ref,
        saved_at=saved_at,
    )


def _to_float_list(embedding: Vector | Iterable[float]) -> list[float]:
    """`register_vector` hands back a pgvector `Vector`, which is not iterable."""
    if isinstance(embedding, Vector):
        return list(embedding.to_list())
    return [float(value) for value in embedding]
