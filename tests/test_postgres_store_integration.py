"""Contract tests for `PostgresReelStore` against a real Postgres/pgvector.

The seam tests in `test_save_reel.py`/`test_ask.py` use an in-memory fake
store, so they cannot catch SQL- or type-adaptation bugs (e.g. sending a
query embedding as `double precision[]`, which has no `<=>` operator). These
tests fill that gap.

Skipped unless TEST_DATABASE_URL (or DATABASE_URL) points at a reachable
instance, so the default `pytest` run stays hermetic per the spec.
"""

from __future__ import annotations

import os
import uuid

import pytest
from dotenv import load_dotenv

from reel_vault.models import SavedReel

load_dotenv()

DSN = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")

# Rows these tests create are prefixed so the fixture can clean up exactly
# what it made, without touching real saved reels.
_TEST_URL_PREFIX = "https://instagram.com/reel/pytest-"


def _reachable(dsn: str | None) -> bool:
    if not dsn:
        return False
    try:
        import psycopg

        with psycopg.connect(dsn, connect_timeout=3):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _reachable(DSN), reason="no reachable Postgres/pgvector instance configured"
)


@pytest.fixture
def store():
    """Yields a real store, then deletes every row these tests created so the
    user's actual vault isn't polluted by a test run."""
    from reel_vault.adapters.postgres_store import PostgresReelStore

    store = PostgresReelStore(DSN)  # type: ignore[arg-type]
    try:
        yield store
    finally:
        store._conn.execute(
            "DELETE FROM saved_reels WHERE normalized_url LIKE %s",
            (f"{_TEST_URL_PREFIX}%",),
        )


def _reel(
    url: str,
    *,
    embedding: list[float],
    tags: list[str] | None = None,
    collection: str = "Testing",
    subcollection: str | None = None,
    author_handle: str | None = None,
    author_name: str | None = None,
) -> SavedReel:
    return SavedReel(
        url=url,
        caption=f"caption for {url}",
        tags=tags if tags is not None else ["test"],
        embedding=embedding,
        collection=collection,
        subcollection=subcollection,
        author_handle=author_handle,
        author_name=author_name,
    )


def _unique_url() -> str:
    return f"{_TEST_URL_PREFIX}{uuid.uuid4().hex[:12]}"


def test_save_then_find_round_trips_all_fields(store) -> None:
    url = _unique_url()
    embedding = [0.1] * 384
    store.save(
        _reel(
            url,
            embedding=embedding,
            tags=["alpha", "beta"],
            collection="AI",
            subcollection="RAG",
            author_handle="someone",
            author_name="Some One",
        )
    )

    found = store.find_by_url(url)

    assert found is not None
    assert found.url == url
    assert found.tags == ["alpha", "beta"]
    assert found.collection == "AI"
    assert found.subcollection == "RAG"
    assert found.author_handle == "someone"
    assert found.author_name == "Some One"
    assert len(found.embedding) == 384
    assert found.embedding == pytest.approx(embedding, abs=1e-6)


def test_known_collections_groups_subcollections_under_their_parent(store) -> None:
    embedding = [0.3] * 384
    store.save(_reel(_unique_url(), embedding=embedding, collection="Zeta", subcollection="One"))
    store.save(_reel(_unique_url(), embedding=embedding, collection="Zeta", subcollection="Two"))
    store.save(_reel(_unique_url(), embedding=embedding, collection="Zeta"))

    known = store.known_collections()

    assert sorted(known["Zeta"]) == ["One", "Two"]


def test_search_results_carry_collection_and_author(store) -> None:
    url = _unique_url()
    embedding = [0.0] * 383 + [1.0]
    store.save(
        _reel(
            url,
            embedding=embedding,
            collection="AI",
            subcollection="Agents",
            author_handle="creator",
        )
    )

    results = store.search(embedding, top_k=1)

    reel, _ = results[0]
    assert reel.collection == "AI"
    assert reel.subcollection == "Agents"
    assert reel.author_handle == "creator"


def test_search_returns_similarity_scores(store) -> None:
    url = _unique_url()
    embedding = [0.0] * 383 + [1.0]
    store.save(_reel(url, embedding=embedding))

    results = store.search(embedding, top_k=5)

    assert results, "expected at least the reel just saved"
    top_reel, top_similarity = results[0]
    assert top_reel.url == url
    assert top_similarity == pytest.approx(1.0, abs=1e-4)


def test_duplicate_save_does_not_create_a_second_row(store) -> None:
    url = _unique_url()
    embedding = [0.2] * 384
    store.save(_reel(url, embedding=embedding, tags=["first"]))
    store.save(_reel(url, embedding=embedding, tags=["second"]))

    found = store.find_by_url(url)

    assert found is not None
    assert found.tags == ["first"]
