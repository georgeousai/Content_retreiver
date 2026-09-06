from __future__ import annotations

from reel_vault.models import (
    AggregateAnswer,
    ListAnswer,
    NoMatch,
    QueryKind,
    Saved,
    SingleItemAnswer,
)
from reel_vault.vault import RetrievalSettings
from tests.conftest import make_vault
from tests.fakes import FakeSummarizer, InMemoryReelStore


def _seeded_vault(**overrides) -> tuple:
    store = InMemoryReelStore()
    vault = make_vault(
        captions={
            "https://instagram.com/reel/1": "transformer architecture explained in depth",
            "https://instagram.com/reel/2": "what is a sourdough starter recipe",
            "https://instagram.com/reel/3": "common ai interview questions about transformers",
        },
        store=store,
        **overrides,
    )
    for url in [
        "https://instagram.com/reel/1",
        "https://instagram.com/reel/2",
        "https://instagram.com/reel/3",
    ]:
        result = vault.save_reel(url)
        assert isinstance(result, Saved)
    return vault, store


def test_single_item_query_returns_the_matching_reel_link_and_tags() -> None:
    vault, _ = _seeded_vault()

    answer = vault.ask("find that reel about transformer architecture")

    assert isinstance(answer, SingleItemAnswer)
    assert answer.reel.url == "https://instagram.com/p/1"


def test_no_match_reply_when_nothing_is_relevant() -> None:
    vault, _ = _seeded_vault(match_threshold=0.99)

    answer = vault.ask("recipes for lasagna")

    assert isinstance(answer, NoMatch)


def test_aggregate_query_synthesizes_answer_from_matched_captions_only() -> None:
    vault, _ = _seeded_vault()

    answer = vault.ask("give me all the interview questions from my ai transformer reels")

    assert isinstance(answer, AggregateAnswer)
    assert "sourdough" not in answer.text
    assert any("interview" in reel.caption for reel in answer.reels)


def test_single_item_behavior_unchanged_when_aggregate_trigger_absent() -> None:
    vault, _ = _seeded_vault()

    answer = vault.ask("transformer architecture reel")

    assert isinstance(answer, SingleItemAnswer)


def _vault_with_many_matching_reels(count: int, **overrides) -> tuple:
    """Seed more reels on one topic than any single cap, so the per-intent
    limits are actually observable."""
    captions = {
        f"https://instagram.com/reel/{i}": f"ai topic reel number{i}" for i in range(count)
    }
    store = InMemoryReelStore()
    vault = make_vault(captions=captions, store=store, **overrides)
    for url in captions:
        assert isinstance(vault.save_reel(url), Saved)
    return vault, store


def test_list_query_returns_the_matched_reels_without_summarizing() -> None:
    """A browse request wants the matches themselves, not a synthesized
    paragraph — and must not spend an LLM call producing one."""
    summarizer = FakeSummarizer()
    vault, _ = _seeded_vault(summarizer=summarizer)

    answer = vault.ask("show me my reels about transformers")

    assert isinstance(answer, ListAnswer)
    assert any("transformer" in reel.caption for reel in answer.reels)
    assert summarizer.calls == []


def test_list_query_is_not_capped_at_the_single_item_limit() -> None:
    """Regression: every query used to share top_k=5, so 'show me all' silently
    dropped everything past the fifth match."""
    vault, _ = _vault_with_many_matching_reels(20)

    answer = vault.ask("show me my ai topic reels")

    assert isinstance(answer, ListAnswer)
    assert len(answer.reels) == 20


def test_aggregate_query_is_capped_below_the_list_limit() -> None:
    """Every matched caption goes into one LLM prompt, so aggregate stays
    bounded well below the (free) list cap."""
    vault, _ = _vault_with_many_matching_reels(20)

    answer = vault.ask("summarize my ai topic reels")

    assert isinstance(answer, AggregateAnswer)
    assert len(answer.reels) == 15


def test_per_intent_caps_are_tunable() -> None:
    vault, _ = _vault_with_many_matching_reels(20, top_k_list=8)

    answer = vault.ask("show me my ai topic reels")

    assert isinstance(answer, ListAnswer)
    assert len(answer.reels) == 8


def test_every_query_kind_has_a_retrieval_cap_decided_for_it() -> None:
    """The caps and the answer-writers are both keyed on `QueryKind`, and a
    kind added to one and forgotten in the other is the drift that keeping
    them in separate cascades invites. This is the guard that makes the
    omission loud at construction rather than a KeyError on whichever query
    happens to be classified as the new kind first."""
    assert set(RetrievalSettings().caps()) == set(QueryKind)
