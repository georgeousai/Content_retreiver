"""Postgres/pgvector-backed `ReelStore`. One row per `SavedReel`."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import timezone

import psycopg
from pgvector import Vector
from pgvector.psycopg import register_vector

from reel_vault.models import SavedReel

SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS saved_reels (
    normalized_url TEXT PRIMARY KEY,
    caption TEXT NOT NULL,
    tags TEXT[] NOT NULL DEFAULT '{}',
    embedding VECTOR(384) NOT NULL,
    saved_at TIMESTAMPTZ NOT NULL
);
"""


class PostgresReelStore:
    def __init__(self, dsn: str) -> None:
        self._conn = psycopg.connect(dsn, autocommit=True)
        register_vector(self._conn)
        self._conn.execute(SCHEMA)

    def find_by_url(self, normalized_url: str) -> SavedReel | None:
        row = self._conn.execute(
            "SELECT normalized_url, caption, tags, embedding, saved_at "
            "FROM saved_reels WHERE normalized_url = %s",
            (normalized_url,),
        ).fetchone()
        return _to_reel(row) if row else None

    def save(self, reel: SavedReel) -> None:
        self._conn.execute(
            "INSERT INTO saved_reels (normalized_url, caption, tags, embedding, saved_at) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (normalized_url) DO NOTHING",
            (reel.url, reel.caption, reel.tags, Vector(reel.embedding), reel.saved_at),
        )

    def search(
        self, query_embedding: list[float], top_k: int
    ) -> list[tuple[SavedReel, float]]:
        # `Vector` is required so the parameter is sent as pgvector's `vector`
        # type; a bare list adapts to `double precision[]`, which has no `<=>`
        # operator.
        vector = Vector(query_embedding)
        rows = self._conn.execute(
            "SELECT normalized_url, caption, tags, embedding, saved_at, "
            "1 - (embedding <=> %s) AS similarity "
            "FROM saved_reels ORDER BY embedding <=> %s LIMIT %s",
            (vector, vector, top_k),
        ).fetchall()
        return [(_to_reel(row[:-1]), row[-1]) for row in rows]


def _to_reel(row: tuple) -> SavedReel:
    normalized_url, caption, tags, embedding, saved_at = row
    saved_at = saved_at if saved_at.tzinfo else saved_at.replace(tzinfo=timezone.utc)
    return SavedReel(
        url=normalized_url,
        caption=caption,
        tags=list(tags),
        embedding=_to_float_list(embedding),
        saved_at=saved_at,
    )


def _to_float_list(embedding: Vector | Iterable[float]) -> list[float]:
    """`register_vector` hands back a pgvector `Vector`, which is not iterable."""
    if isinstance(embedding, Vector):
        return list(embedding.to_list())
    return [float(value) for value in embedding]
