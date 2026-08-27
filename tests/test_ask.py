from __future__ import annotations

from reel_vault.models import AggregateAnswer, NoMatch, Saved, SingleItemAnswer
from tests.conftest import make_vault
from tests.fakes import InMemoryReelStore


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
    assert answer.reel.url == "https://instagram.com/reel/1"


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
