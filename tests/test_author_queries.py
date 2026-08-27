"""Seam-level tests for asking after a creator rather than a topic."""

from __future__ import annotations

from reel_vault.models import ExtractedPost, ListAnswer, Saved
from tests.conftest import make_vault
from tests.fakes import FakeEmbedder, InMemoryReelStore

POSTS = {
    "https://instagram.com/reel/1": ExtractedPost(
        caption="deadlift form breakdown",
        author_handle="gymshark",
        author_name="Gymshark",
    ),
    "https://instagram.com/reel/2": ExtractedPost(
        caption="protein timing myths",
        author_handle="gymshark",
        author_name="Gymshark",
    ),
    "https://instagram.com/reel/3": ExtractedPost(
        caption="transformer architecture explained",
        author_handle="ai_explains",
        author_name="Andrew Huberman",
    ),
}


def _seeded_vault(**overrides) -> tuple:
    store = InMemoryReelStore()
    embedder = FakeEmbedder()
    vault = make_vault(captions=POSTS, store=store, embedder=embedder, **overrides)
    for url in POSTS:
        assert isinstance(vault.save_reel(url), Saved)
    embedder.calls.clear()  # ignore the embeds that saving performed
    store.search_calls.clear()
    return vault, store, embedder


def test_author_query_returns_every_reel_by_that_creator() -> None:
    vault, _, _ = _seeded_vault()

    answer = vault.ask("show me @gymshark's reels")

    assert isinstance(answer, ListAnswer)
    assert {reel.url for reel in answer.reels} == {
        "https://instagram.com/reel/1",
        "https://instagram.com/reel/2",
    }


def test_author_query_ignores_topic_similarity_entirely() -> None:
    """The creator's reels are about unrelated things; an author query must
    return them all rather than ranking them against the query text."""
    vault, store, embedder = _seeded_vault()

    answer = vault.ask("show me @gymshark's reels")

    assert isinstance(answer, ListAnswer)
    assert len(answer.reels) == 2
    assert embedder.calls == []
    assert store.search_calls == []


def test_author_query_matches_the_display_name_too() -> None:
    vault, _, _ = _seeded_vault()

    answer = vault.ask("what have I saved from @Andrew Huberman")

    assert isinstance(answer, ListAnswer)
    assert [reel.url for reel in answer.reels] == ["https://instagram.com/reel/3"]


def test_author_with_nothing_saved_returns_an_empty_list_not_an_error() -> None:
    vault, _, _ = _seeded_vault()

    answer = vault.ask("show me @nobody's reels")

    assert isinstance(answer, ListAnswer)
    assert answer.reels == []
    assert answer.author == "nobody"
