"""Seam-level tests for asking after a creator rather than a topic."""

from __future__ import annotations

from reel_vault.models import AggregateAnswer, ExtractedPost, ListAnswer, Saved
from tests.conftest import make_vault
from tests.fakes import FakeEmbedder, FakeSummarizer, InMemoryReelStore

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
        "https://instagram.com/p/1",
        "https://instagram.com/p/2",
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
    assert [reel.url for reel in answer.reels] == ["https://instagram.com/p/3"]


def test_author_with_nothing_saved_returns_an_empty_list_not_an_error() -> None:
    vault, _, _ = _seeded_vault()

    answer = vault.ask("show me @nobody's reels")

    assert isinstance(answer, ListAnswer)
    assert answer.reels == []
    assert answer.author == "nobody"


def test_aggregate_summarizer_is_given_each_caption_with_its_author() -> None:
    """Without the author reaching the summarizer, no "which creator said
    what" question is answerable at all — so assert it actually arrives."""
    summarizer = FakeSummarizer()
    vault, _, _ = _seeded_vault(summarizer=summarizer)

    answer = vault.ask("summarize my reels about deadlift and protein")

    assert isinstance(answer, AggregateAnswer)
    _, sources = summarizer.calls[-1]
    assert {(s.caption, s.author_handle) for s in sources} >= {
        ("deadlift form breakdown", "gymshark"),
        ("protein timing myths", "gymshark"),
    }
    assert all(s.author_name == "Gymshark" for s in sources if s.author_handle == "gymshark")


def test_summarizer_only_ever_sees_the_matched_reels() -> None:
    """Attribution must come from the matched captions, never from reels the
    query didn't match — the summarizer can't invent what it never saw."""
    summarizer = FakeSummarizer()
    vault, _, _ = _seeded_vault(summarizer=summarizer, match_threshold=0.3)

    vault.ask("summarize my transformer architecture reels")

    _, sources = summarizer.calls[-1]
    assert [s.caption for s in sources] == ["transformer architecture explained"]
