"""Retrieval matches captions by meaning and curated metadata by word.

Straight from a live failure: "reels about interview prep" answered "Nothing
in the vault matches that" while a reel filed under Product Management >
Interviews, tagged "case prep", sat in the vault. It scored 0.330 against the
0.35 threshold, because only its caption was ever searched and its caption
never says "interview".
"""

from __future__ import annotations

from reel_vault.models import ExtractedPost, ListAnswer, NoMatch, Saved, SavedReel
from reel_vault.vault import DEFAULT_MATCH_THRESHOLD
from reel_vault.search import (
    KEYWORD_WEIGHT,
    embedding_text,
    keyword_score,
    merge_hits,
    metadata_text,
    search_terms,
)
from tests.conftest import make_vault
from tests.fakes import FakeCollectionAssigner, FakeEmbedder, InMemoryReelStore
from reel_vault.models import CollectionAssignment

# A reel whose caption shares no word with the query it should answer. Every
# word linking it to "interview prep" lives in metadata the old search never
# looked at.
FILED_BUT_UNSPOKEN = "https://instagram.com/p/filed"
UNRELATED = "https://instagram.com/p/other"

POSTS = {
    FILED_BUT_UNSPOKEN: ExtractedPost(
        caption="5yrs ago this wasn't a thing", author_handle="steveofallstreets"
    ),
    UNRELATED: ExtractedPost(caption="4 bicep hacks", author_handle="supacoopaaa"),
}
ASSIGNMENTS = {
    "5yrs ago this wasn't a thing": CollectionAssignment(
        collection="Product Management", subcollection="Interviews"
    ),
    "4 bicep hacks": CollectionAssignment(collection="Fitness", subcollection="Arms"),
}
TAGS = {"5yrs ago this wasn't a thing": ["hiring"], "4 bicep hacks": ["arms"]}


def _seeded_vault(**overrides):
    """Seeded at the production match threshold. `make_vault` defaults to a
    much lower one so bag-of-words fake embeddings clear it, but every test
    here is about where the cutoff actually falls."""
    overrides.setdefault("match_threshold", DEFAULT_MATCH_THRESHOLD)
    vault = make_vault(
        captions=POSTS, assignments=ASSIGNMENTS, tags_by_caption=TAGS, **overrides
    )
    for url in POSTS:
        assert isinstance(vault.save_reel(url), Saved)
    return vault


# --- the pure definitions both stores share -------------------------------


def test_a_reel_is_embedded_with_its_shelf_and_tags_not_just_its_caption() -> None:
    text = embedding_text(
        "5yrs ago this wasn't a thing", ["hiring"], "Product Management", "Interviews"
    )

    assert "Product Management" in text
    assert "Interviews" in text
    assert "hiring" in text
    assert "5yrs ago this wasn't a thing" in text


def test_the_keyword_half_of_a_reel_excludes_its_caption() -> None:
    """The caption is long free-form prose that shares words with any query by
    chance; letting it into the keyword arm would let a coincidence outrank a
    reel the vault deliberately filed under the word asked for."""
    text = metadata_text(["hiring"], "Product Management", "Interviews")

    assert "Interviews" in text
    assert "hiring" in text
    assert "5yrs" not in text


def test_framing_words_are_not_treated_as_search_terms() -> None:
    """Terms are scored by what fraction of them a reel matched, so leaving
    "show me all my ... reels" in would make relevance depend on how chattily
    the question happened to be phrased."""
    assert search_terms("show me all my interview prep reels") == ["interview", "prep"]


def test_search_terms_are_reduced_to_bare_words_and_deduplicated() -> None:
    """They are handed to Postgres's `to_tsquery`, which reads its input as an
    expression — punctuation there is a syntax error, not a search."""
    assert search_terms("@gymshark's DEADLIFT: deadlift & form!") == [
        "gymshark",
        "deadlift",
        "form",
    ]


def test_a_keyword_hit_is_scored_by_how_much_of_the_query_it_accounts_for() -> None:
    assert keyword_score(2, 2) == KEYWORD_WEIGHT
    assert keyword_score(1, 2) == KEYWORD_WEIGHT / 2
    assert keyword_score(0, 4) == 0.0
    assert keyword_score(1, 0) == 0.0


def test_matching_by_both_meaning_and_word_does_not_inflate_a_reels_score() -> None:
    """The two arms are two ways of asking the same question. Summing them
    would push a reel that matches weakly twice above one that is a strong
    answer on either count alone."""
    reel = SavedReel(url="u", caption="c", tags=[], embedding=[])

    merged = merge_hits([(reel, 0.5)], [(reel, 0.4)], top_k=5)

    assert merged == [(reel, 0.5)]


# --- the seam --------------------------------------------------------------


def test_a_reel_is_found_by_the_shelf_it_was_filed_on(  # the live failure
) -> None:
    """Its caption says nothing about interviews; its sub-collection is named
    Interviews. Before hybrid retrieval this query returned nothing."""
    vault = _seeded_vault()

    answer = vault.ask("show me my interview prep reels")

    assert isinstance(answer, ListAnswer)
    assert [reel.url for reel in answer.reels] == [FILED_BUT_UNSPOKEN]


def test_a_reel_is_found_by_a_tag_the_caption_never_uses() -> None:
    vault = _seeded_vault()

    answer = vault.ask("show me my hiring reels")

    assert isinstance(answer, ListAnswer)
    assert [reel.url for reel in answer.reels] == [FILED_BUT_UNSPOKEN]


def test_one_incidental_word_in_a_long_query_does_not_drag_a_reel_in() -> None:
    """Coverage is what separates an answer from a coincidence: matching one
    of four terms scores 0.2, under the 0.35 threshold, so a reel filed under
    a word the query merely brushes past stays out."""
    vault = _seeded_vault()

    answer = vault.ask("show me reels about interview lighting camera microphone")

    assert isinstance(answer, NoMatch)


def test_a_query_matching_no_metadata_still_searches_captions() -> None:
    """The keyword arm is an addition, not a replacement — a reel whose words
    live only in its caption must stay reachable, and must still rank first.

    Run at `make_vault`'s lower threshold: "bicep" appears in no metadata at
    all, so this is the semantic arm on its own, and the fake embedder's
    bag-of-words scores are far below what a real model returns.
    """
    vault = _seeded_vault(match_threshold=0.05)

    answer = vault.ask("show me my bicep reels")

    assert isinstance(answer, ListAnswer)
    assert answer.reels[0].url == UNRELATED
