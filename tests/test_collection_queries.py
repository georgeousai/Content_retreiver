"""Seam-level tests for asking after a collection by name.

Every reel is filed into exactly one collection at save time. Asking for "my
Sales reels" is therefore a lookup on that shelf, not a similarity search —
these tests come straight from live failures where it was the latter.
"""

from __future__ import annotations

import pytest

from reel_vault.models import (
    AggregateAnswer,
    CollectionAssignment,
    CompareAnswer,
    ExtractedPost,
    ListAnswer,
    NoMatch,
    QueryClassification,
    QueryKind,
    Saved,
    SingleItemAnswer,
)
from reel_vault.search import search_terms, terms_beyond_the_shelf
from reel_vault.vault import DEFAULT_MATCH_THRESHOLD
from tests.conftest import make_vault
from tests.fakes import (
    FakeComparer,
    FakeQueryIntent,
    FakeSummarizer,
    InMemoryReelStore,
)

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


def _shelf_scoped_single(query: str, collection: str = "Sales") -> FakeQueryIntent:
    """A query the classifier read as "one reel, off this shelf" — the shape
    the real prompt produces for any specific question that names a shelf."""
    return FakeQueryIntent(
        classifications={
            query: QueryClassification(kind=QueryKind.SINGLE, collection=collection)
        }
    )


def _sales_vault_saved_in_order(*urls: str, query: str, **overrides) -> tuple:
    store = InMemoryReelStore()
    vault = make_vault(
        captions=POSTS,
        assignments=ASSIGNMENTS,
        store=store,
        query_intent=_shelf_scoped_single(query),
        **overrides,
    )
    for url in urls:
        assert isinstance(vault.save_reel(url), Saved)
    return vault, store


def test_a_specific_question_about_a_shelf_is_answered_by_the_question() -> None:
    """Naming a shelf scopes a single-item question; it does not answer it.

    The shelf was read instead of searched, so "that Sales reel about being
    asked where you got my number" came back as whichever Sales reel the
    store handed over first, with the rest of the question discarded. The
    two Sales reels are saved in the order that makes the first row the
    wrong one, since a shelf whose first row happens to be right cannot
    tell the bug from the fix.
    """
    query = "that Sales reel about a cold caller being asked where you got my number"
    vault, _ = _sales_vault_saved_in_order(
        "https://instagram.com/reel/s2",
        "https://instagram.com/reel/s1",
        query=query,
    )

    answer = vault.ask(query)

    assert isinstance(answer, SingleItemAnswer)
    assert answer.reel.url == "https://instagram.com/p/s1"


def test_naming_a_shelf_does_not_outrank_the_reel_the_question_describes() -> None:
    """The shelf is a scope, not a verdict. It still counts — the keyword arm
    matches a reel's collection, so every Sales reel is boosted for being one
    — but a reel the question actually describes outranks reels whose only
    claim is the shelf name the user said."""
    query = "the Sales reel about bicep hacks for small arms"
    vault, _ = _sales_vault_saved_in_order(
        "https://instagram.com/reel/s1",
        "https://instagram.com/reel/s2",
        "https://instagram.com/reel/f1",
        query=query,
    )

    answer = vault.ask(query)

    assert isinstance(answer, SingleItemAnswer)
    assert answer.reel.url == "https://instagram.com/p/f1"


def test_a_single_question_naming_a_shelf_still_reports_nothing_when_nothing_matches() -> None:
    query = "the Sales reel about repairing a bicycle puncture"
    vault, _ = _sales_vault_saved_in_order(
        "https://instagram.com/reel/s1", query=query, match_threshold=0.99
    )

    assert isinstance(vault.ask(query), NoMatch)


# --- a question *within* a shelf, as opposed to a request *for* it ----------
#
# Live failure, 2026-09-06: "Travel plans for Arambol" answered with every
# reel on the Travel shelf. Naming the shelf sent the query straight to the
# shelf, and the rest of the question was discarded.

TRAVEL_POSTS = {
    "https://instagram.com/reel/t1": ExtractedPost(
        caption="Arambol beaches in Goa travel plans for 3 days",
        author_handle="goawanderer",
    ),
    "https://instagram.com/reel/t2": ExtractedPost(
        caption="Kerala backwaters houseboat itinerary over 5 days",
        author_handle="southbound",
    ),
    "https://instagram.com/reel/t3": ExtractedPost(
        caption="Ladakh bike trip route and permits",
        author_handle="highpassrider",
    ),
}
TRAVEL_URLS = {
    "https://instagram.com/p/t1",
    "https://instagram.com/p/t2",
    "https://instagram.com/p/t3",
}
ALL_ASSIGNMENTS = {
    **ASSIGNMENTS,
    **{
        post.caption: CollectionAssignment(collection="Travel")
        for post in TRAVEL_POSTS.values()
    },
}


def _shelf_scoped(query: str, kind: QueryKind, collection: str = "Travel") -> FakeQueryIntent:
    """The classifier's reading of a query that names a shelf: the shape of
    answer asked for, and the shelf. It never says whether the shelf was the
    whole request -- that is the vault's call."""
    return FakeQueryIntent(
        classifications={
            query: QueryClassification(kind=kind, collection=collection)
        }
    )


def _travel_vault(query: str, kind: QueryKind, **overrides) -> tuple:
    """Sales, Fitness and Travel shelves, and a query classified as given.

    At the production relevance floor, not `make_vault`'s permissive
    default: whether a within-shelf ranking keeps only the reel asked about
    is exactly what the floor decides.
    """
    overrides.setdefault("match_threshold", DEFAULT_MATCH_THRESHOLD)
    store = InMemoryReelStore()
    vault = make_vault(
        captions={**POSTS, **TRAVEL_POSTS},
        assignments=ALL_ASSIGNMENTS,
        store=store,
        query_intent=_shelf_scoped(query, kind),
        **overrides,
    )
    for url in [*POSTS, *TRAVEL_POSTS]:
        assert isinstance(vault.save_reel(url), Saved)
    return vault, store


def test_a_question_within_a_shelf_returns_only_the_reels_it_describes() -> None:
    """The live failure itself. Three reels on Travel; one is about Arambol."""
    query = "Travel plans for Arambol"
    vault, _ = _travel_vault(query, QueryKind.LIST)

    answer = vault.ask(query)

    assert isinstance(answer, ListAnswer)
    assert answer.collection == "Travel"
    assert [reel.url for reel in answer.reels] == ["https://instagram.com/p/t1"]


@pytest.mark.parametrize(
    "query, kind",
    [
        ("show me all my Travel reels", QueryKind.LIST),
        ("list everything in Travel", QueryKind.LIST),
        ("summarize what my Travel reels said, grouped by creator", QueryKind.AGGREGATE),
        ("which of my Travel reels is best", QueryKind.COMPARE_RANK),
    ],
)
def test_asking_for_the_shelf_itself_still_gets_all_of_it(
    query: str, kind: QueryKind
) -> None:
    """Words about the *shape* of the answer -- list it, summarize it, pick
    the best -- are not a topic to rank the shelf against. Every one of
    these wants the whole shelf, and a similarity floor applied to them
    would drop the reels whose captions happen not to resemble the phrasing
    (the "5yrs ago this wasn't a thing" problem again)."""
    vault, _ = _travel_vault(query, kind)

    answer = vault.ask(query)

    assert isinstance(answer, (ListAnswer, AggregateAnswer, CompareAnswer))
    assert {reel.url for reel in answer.reels} == TRAVEL_URLS


def test_a_ranked_question_within_a_shelf_ranks_only_the_reels_it_describes() -> None:
    """The comparer is asked about the reels that fit the question, not the
    whole shelf with the question left for it to re-apply."""
    query = "best Travel reel about Goa beaches"
    comparer = FakeComparer()
    vault, _ = _travel_vault(query, QueryKind.COMPARE_RANK, comparer=comparer)

    answer = vault.ask(query)

    assert isinstance(answer, CompareAnswer)
    _, sources = comparer.calls[-1]
    assert [source.author_handle for source in sources] == ["goawanderer"]


def test_a_shelf_question_nothing_on_the_shelf_answers_falls_back_to_the_whole_vault() -> None:
    """The shelf is a scope, not a verdict. Someone who misremembers which
    shelf a reel is on should still get the reel -- from wherever it is --
    and never a worse answer than plain search would have given."""
    query = "Travel reels about bicep hacks for small arms"
    vault, _ = _travel_vault(query, QueryKind.LIST)

    answer = vault.ask(query)

    assert isinstance(answer, ListAnswer)
    assert answer.collection is None
    assert [reel.url for reel in answer.reels] == ["https://instagram.com/p/f1"]


@pytest.mark.parametrize(
    "query, collection, residue",
    [
        # The shelf is the whole request.
        ("show me all my Sales reels", "Sales", []),
        ("summarize what my Sales reels said, grouped by creator", "Sales", []),
        ("which of my Travel reels is best", "Travel", []),
        ("list everything in Travel", "Travel", []),
        # A multi-word shelf, named in part.
        ("my strength reels", "Strength Training", []),
        # A topic within the shelf.
        ("Travel plans for Arambol", "Travel", ["plans", "arambol"]),
        ("Sales reels about cold calling", "Sales", ["cold", "calling"]),
        ("best Travel reel about Goa beaches", "Travel", ["goa", "beaches"]),
    ],
)
def test_what_a_shelf_query_asks_for_beyond_the_shelf(
    query: str, collection: str, residue: list[str]
) -> None:
    assert terms_beyond_the_shelf(query, collection) == residue


def test_answer_shape_words_still_count_for_keyword_search() -> None:
    """"creator" is noise in "grouped by creator" and a real term in a query
    about creators. Only the shelf-or-topic decision drops it; the keyword
    arm's coverage goes on scoring it."""
    assert "creator" in search_terms("reels about creator monetization")
    assert terms_beyond_the_shelf("Sales reels grouped by creator", "Sales") == []
