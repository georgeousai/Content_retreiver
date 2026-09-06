"""Seam-level tests for the two answer shapes the vault could not produce.

Ranking has to pick a winner and say by what measure; compiling has to pull
one specific thing out of many reels and merge the duplicates. Both used to
fall to the summarizer, whose job is to write prose — these assert they no
longer do, since one prompt left to infer its own answer shape is what
produced the hallucination already on record.
"""

from __future__ import annotations

import pytest

from reel_vault.models import (
    AggregateAnswer,
    CompareAnswer,
    ExtractAnswer,
    ExtractedPost,
    MediaExtraction,
    NoMatch,
    Saved,
)
from tests.conftest import make_vault
from tests.fakes import (
    FakeComparer,
    FakeItemExtractor,
    FakeSummarizer,
    InMemoryReelStore,
)

POSTS = {
    "https://instagram.com/reel/A": ExtractedPost(
        caption="bicep curl form tips", author_handle="liftcoach"
    ),
    "https://instagram.com/reel/B": ExtractedPost(
        caption="bicep hammer curl routine", author_handle="gymnerd"
    ),
}


@pytest.fixture
def store() -> InMemoryReelStore:
    return InMemoryReelStore()


def _seeded(store: InMemoryReelStore, **overrides):
    vault = make_vault(captions=POSTS, store=store, **overrides)
    for url in POSTS:
        assert isinstance(vault.save_reel(url), Saved)
    return vault


def test_a_ranking_question_names_what_it_ranked_by(store: InMemoryReelStore) -> None:
    """An answer that hides its criterion cannot be disagreed with, and the
    vault deliberately states one instead of asking a question back."""
    vault = _seeded(store)

    answer = vault.ask("best bicep exercise")

    assert isinstance(answer, CompareAnswer)
    assert answer.criterion
    assert answer.reels


def test_a_ranking_question_never_reaches_the_summarizer(
    store: InMemoryReelStore,
) -> None:
    summarizer = FakeSummarizer()
    comparer = FakeComparer()
    vault = _seeded(store, summarizer=summarizer, comparer=comparer)

    vault.ask("best bicep exercise")

    assert summarizer.calls == []
    assert len(comparer.calls) == 1


def test_a_compilation_question_returns_items_deduplicated_across_reels(
    store: InMemoryReelStore,
) -> None:
    vault = _seeded(store, condenser=None)
    # Both reels say the same thing; the compiled list should say it once.
    vault.attach_media(
        "https://instagram.com/reel/A", MediaExtraction(transcript="keep elbows pinned")
    )
    vault.attach_media(
        "https://instagram.com/reel/B", MediaExtraction(transcript="keep elbows pinned")
    )

    answer = vault.ask("compile the bicep cues")

    assert isinstance(answer, ExtractAnswer)
    assert answer.items.count("keep elbows pinned") == 1


def test_a_compilation_question_never_reaches_the_summarizer(
    store: InMemoryReelStore,
) -> None:
    summarizer = FakeSummarizer()
    extractor = FakeItemExtractor()
    vault = _seeded(store, summarizer=summarizer, item_extractor=extractor)

    vault.ask("compile the bicep cues")

    assert summarizer.calls == []
    assert len(extractor.calls) == 1


def test_both_new_kinds_see_what_the_video_said(store: InMemoryReelStore) -> None:
    """Story 10 of the spec: these answer from the video too, not only the
    caption. Asserting on what the adapter was handed is the only way to see
    it, and is the behaviour under test."""
    comparer = FakeComparer()
    vault = _seeded(store, comparer=comparer)
    vault.attach_media(
        "https://instagram.com/reel/A",
        MediaExtraction(transcript="do six sets", frame_analysis="on screen: 6 SETS"),
    )

    vault.ask("best bicep exercise")

    _, sources = comparer.calls[0]
    carried = [source for source in sources if source.transcript]
    assert carried and carried[0].transcript == "do six sets"
    assert carried[0].frame_text == "on screen: 6 SETS"


def test_a_ranking_question_matching_nothing_says_so(store: InMemoryReelStore) -> None:
    comparer = FakeComparer()
    vault = _seeded(store, comparer=comparer, match_threshold=0.99)

    assert isinstance(vault.ask("best sourdough starter"), NoMatch)
    assert comparer.calls == []


def test_a_compilation_question_matching_nothing_says_so(
    store: InMemoryReelStore,
) -> None:
    extractor = FakeItemExtractor()
    vault = _seeded(store, item_extractor=extractor, match_threshold=0.99)

    assert isinstance(vault.ask("compile the sourdough steps"), NoMatch)
    assert extractor.calls == []


def test_synthesizing_still_goes_to_the_summarizer(store: InMemoryReelStore) -> None:
    """The existing kinds are untouched by the two new ones."""
    summarizer = FakeSummarizer()
    vault = _seeded(store, summarizer=summarizer)

    answer = vault.ask("summarize my bicep reels")

    assert isinstance(answer, AggregateAnswer)
    assert len(summarizer.calls) == 1


def test_a_named_collection_can_still_be_ranked(store: InMemoryReelStore) -> None:
    """Naming a shelf scopes retrieval; it does not change what shape of
    answer was asked for."""
    vault = _seeded(store)
    vault.refile("https://instagram.com/reel/A", collection="Fitness")

    answer = vault.ask("best exercise in Fitness")

    assert isinstance(answer, CompareAnswer)
    assert [reel.url for reel in answer.reels] == ["https://instagram.com/p/A"]
