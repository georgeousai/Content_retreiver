"""Postgres/pgvector-backed `ReelStore`. One row per `SavedReel`."""

from __future__ import annotations

from datetime import datetime, timezone

import psycopg
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
            (reel.url, reel.caption, reel.tags, reel.embedding, reel.saved_at),
        )

    def search(
        self, query_embedding: list[float], top_k: int
    ) -> list[tuple[SavedReel, float]]:
        rows = self._conn.execute(
            "SELECT normalized_url, caption, tags, embedding, saved_at, "
            "1 - (embedding <=> %s) AS similarity "
            "FROM saved_reels ORDER BY embedding <=> %s LIMIT %s",
            (query_embedding, query_embedding, top_k),
        ).fetchall()
        return [(_to_reel(row[:-1]), row[-1]) for row in rows]


def _to_reel(row: tuple) -> SavedReel:
    normalized_url, caption, tags, embedding, saved_at = row
    saved_at = saved_at if saved_at.tzinfo else saved_at.replace(tzinfo=timezone.utc)
    return SavedReel(
        url=normalized_url,
        caption=caption,
        tags=list(tags),
        embedding=list(embedding),
        saved_at=saved_at,
    )
