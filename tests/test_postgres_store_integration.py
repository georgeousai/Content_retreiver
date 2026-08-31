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
    thumbnail_ref: str | None = None,
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
        thumbnail_ref=thumbnail_ref,
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
            thumbnail_ref="AgACAgQAAx-file-id",
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
    assert found.thumbnail_ref == "AgACAgQAAx-file-id"
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

    results = store.search(embedding, [], top_k=1)

    reel, _ = results[0]
    assert reel.collection == "AI"
    assert reel.subcollection == "Agents"
    assert reel.author_handle == "creator"


def test_search_returns_similarity_scores(store) -> None:
    url = _unique_url()
    embedding = [0.0] * 383 + [1.0]
    store.save(_reel(url, embedding=embedding))

    results = store.search(embedding, [], top_k=5)

    assert results, "expected at least the reel just saved"
    top_reel, top_similarity = results[0]
    assert top_reel.url == url
    assert top_similarity == pytest.approx(1.0, abs=1e-4)


def test_find_by_author_matches_handle_or_display_name_case_insensitively(store) -> None:
    embedding = [0.4] * 384
    handle = f"pytest_handle_{uuid.uuid4().hex[:8]}"
    display = f"Pytest Display {uuid.uuid4().hex[:8]}"
    by_handle = _unique_url()
    by_name = _unique_url()
    store.save(_reel(by_handle, embedding=embedding, author_handle=handle))
    store.save(_reel(by_name, embedding=embedding, author_name=display))
    store.save(_reel(_unique_url(), embedding=embedding, author_handle="someone_else"))

    assert [r.url for r in store.find_by_author(handle.upper())] == [by_handle]
    assert [r.url for r in store.find_by_author(display.lower())] == [by_name]
    # A leading @ is how the user types it; it must not defeat the match.
    assert [r.url for r in store.find_by_author(f"@{handle}")] == [by_handle]


def test_find_by_collection_returns_the_whole_shelf_case_insensitively(store) -> None:
    embedding = [0.6] * 384
    collection = f"Pytest{uuid.uuid4().hex[:8]}"
    first, second = _unique_url(), _unique_url()
    store.save(_reel(first, embedding=embedding, collection=collection))
    store.save(_reel(second, embedding=embedding, collection=collection))
    store.save(_reel(_unique_url(), embedding=embedding, collection="Other"))

    found = store.find_by_collection(collection.lower())

    assert {reel.url for reel in found} == {first, second}


def test_set_thumbnail_ref_attaches_a_picture_to_an_existing_reel(store) -> None:
    url = _unique_url()
    store.save(_reel(url, embedding=[0.5] * 384))
    assert store.find_by_url(url).thumbnail_ref is None

    store.set_thumbnail_ref(url, "AgACAgQAAx-file-id")

    assert store.find_by_url(url).thumbnail_ref == "AgACAgQAAx-file-id"


def test_find_by_author_returns_empty_for_an_unknown_creator(store) -> None:
    assert store.find_by_author(f"nobody_{uuid.uuid4().hex[:8]}") == []


def test_duplicate_save_does_not_create_a_second_row(store) -> None:
    url = _unique_url()
    embedding = [0.2] * 384
    store.save(_reel(url, embedding=embedding, tags=["first"]))
    store.save(_reel(url, embedding=embedding, tags=["second"]))

    found = store.find_by_url(url)

    assert found is not None
    assert found.tags == ["first"]


def test_it_builds_its_own_schema_on_a_brand_new_database() -> None:
    """The README's promise: "The app creates the `vector` extension and the
    `saved_reels` table itself on first run."

    It could not. `register_vector` has to look the `vector` type up in the
    database, and it ran before the `CREATE EXTENSION` that makes one, so a
    first run against an empty database died with "vector type not found in
    the database". Every existing vault already had the extension, so the
    only way to see it is to point the store at a database that has never
    held one -- which is what this test does, on a database it creates and
    drops.
    """
    import psycopg

    from reel_vault.adapters.postgres_store import PostgresReelStore

    # The module-level skipif already guarantees this; the assert is for the
    # type checker, which cannot see that far.
    assert DSN is not None
    name = f"reel_vault_pytest_{uuid.uuid4().hex[:12]}"
    server = DSN.rsplit("/", 1)[0]
    admin_dsn = f"{server}/postgres"
    fresh_dsn = f"{server}/{name}"

    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        admin.execute(f"CREATE DATABASE {name}")
    try:
        store = PostgresReelStore(fresh_dsn)
        # Reached at all means the extension existed by the time
        # `register_vector` looked, and that the table was created after it.
        assert store.find_by_url("https://instagram.com/p/nothing-here") is None
        store._conn.close()
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            admin.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
