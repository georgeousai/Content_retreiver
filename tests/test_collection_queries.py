"""Seam-level tests for asking after a collection by name.

Every reel is filed into exactly one collection at save time. Asking for "my
Sales reels" is therefore a lookup on that shelf, not a similarity search —
these tests come straight from live failures where it was the latter.
"""

from __future__ import annotations

from reel_vault.models import (
    AggregateAnswer,
    CollectionAssignment,
    ExtractedPost,
    ListAnswer,
    NoMatch,
    Saved,
)
from tests.conftest import make_vault
from tests.fakes import FakeSummarizer, InMemoryReelStore

POSTS = {
    "https://instagram.com/reel/s1": ExtractedPost(
        caption="Where did you get my number from? Every cold caller's least favourite question",
        author_handle="thegeomethod_",
    ),
    # The reason similarity search cannot do this job: filed under Sales by
    # the user, but the caption says nothing a sales query could match.
    "https://instagram.com/reel/s2": ExtractedPost(
        caption="5yrs ago this wasn't a thing",
        author_handle="steveofallstreets",
    ),
    "https://instagram.com/reel/f1": ExtractedPost(
        caption="4 bicep hacks to fix small arms",
        author_handle="supacoopaaa",
    ),
}
ASSIGNMENTS = {
    POSTS["https://instagram.com/reel/s1"].caption: CollectionAssignment(collection="Sales"),
    POSTS["https://instagram.com/reel/s2"].caption: CollectionAssignment(collection="Sales"),
    POSTS["https://instagram.com/reel/f1"].caption: CollectionAssignment(collection="Fitness"),
}


def _seeded_vault(**overrides) -> tuple:
    store = InMemoryReelStore()
    vault = make_vault(
        captions=POSTS, assignments=ASSIGNMENTS, store=store, **overrides
    )
    for url in POSTS:
        assert isinstance(vault.save_reel(url), Saved)
    return vault, store


def test_listing_a_collection_returns_everything_on_that_shelf() -> None:
    """Live failure: "show me all my sales reels" answered "Nothing in the
    vault matches that" while two Sales reels sat in the vault."""
    vault, _ = _seeded_vault()

    answer = vault.ask("show me all my Sales reels")

    assert isinstance(answer, ListAnswer)
    assert answer.collection == "Sales"
    assert {reel.url for reel in answer.reels} == {
        "https://instagram.com/p/s1",
        "https://instagram.com/p/s2",
    }


def test_a_collection_list_is_not_filtered_by_similarity() -> None:
    """The caption "5yrs ago this wasn't a thing" will never score close to a
    query about sales — but the user filed it under Sales, so it belongs."""
    vault, _ = _seeded_vault(match_threshold=0.99)

    answer = vault.ask("show me all my Sales reels")

    assert isinstance(answer, ListAnswer)
    assert len(answer.reels) == 2


def test_a_collection_never_leaks_reels_from_another_collection() -> None:
    vault, _ = _seeded_vault()

    answer = vault.ask("show me all my Sales reels")

    assert isinstance(answer, ListAnswer)
    assert all(reel.collection == "Sales" for reel in answer.reels)


def test_collection_name_is_matched_regardless_of_capitalisation() -> None:
    vault, _ = _seeded_vault()

    answer = vault.ask("show me all my sales reels")

    assert isinstance(answer, ListAnswer)
    assert answer.collection == "Sales"


def test_summarizing_a_collection_sees_every_reel_on_the_shelf() -> None:
    """Live failure: "what have my sales reels said, grouped by creator"
    summarized one of the two."""
    summarizer = FakeSummarizer()
    vault, _ = _seeded_vault(summarizer=summarizer)

    answer = vault.ask("summarize what my Sales reels said, grouped by creator")

    assert isinstance(answer, AggregateAnswer)
    assert len(answer.reels) == 2
    _, sources = summarizer.calls[-1]
    assert {source.author_handle for source in sources} == {
        "thegeomethod_",
        "steveofallstreets",
    }


def test_a_collection_the_vault_does_not_have_is_not_treated_as_a_shelf() -> None:
    """Naming a shelf that doesn't exist must fall through to semantic search
    rather than returning an empty shelf as though it were real."""
    vault, _ = _seeded_vault(match_threshold=0.99)

    answer = vault.ask("show me all my Cooking reels")

    assert isinstance(answer, NoMatch)


def test_a_topic_that_is_not_a_collection_still_searches_semantically() -> None:
    """"reels about biceps" names no shelf — it must not be treated as one."""
    vault, _ = _seeded_vault()

    answer = vault.ask("show me my reels about bicep hacks")

    assert isinstance(answer, ListAnswer)
    assert answer.collection is None
    assert any("bicep" in reel.caption for reel in answer.reels)
