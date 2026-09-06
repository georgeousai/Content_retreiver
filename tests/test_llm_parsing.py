"""Unit tests for the chat adapters' reply parsing.

No network: these exercise the pure parsing functions. They exist because an
unparsed reply is never an error the user sees — it is silently the wrong
answer shape, which is the worst way for this to fail.
"""

from __future__ import annotations

import pytest

from reel_vault.adapters.llm import (
    _format_source,
    _parse_assignment,
    _parse_classification,
    _parse_kept_indices,
    _parse_tag_list,
    _question_with_numbered_sources,
)
from reel_vault.models import UNCATEGORIZED, QueryKind, SummarySource


@pytest.mark.parametrize(
    "content",
    [
        '{"kind": "LIST", "author": null}',
        '```json\n{"kind": "LIST", "author": null}\n```',
        '```\n{"kind": "LIST", "author": null}\n```',
        'Sure! Here is the classification:\n{"kind": "LIST", "author": null}',
    ],
)
def test_classification_survives_the_wrappers_chat_models_add(content: str) -> None:
    assert _parse_classification(content).kind is QueryKind.LIST


def test_classification_extracts_the_author_and_drops_the_at_sign() -> None:
    result = _parse_classification('{"kind": "AUTHOR_FILTER", "author": "@gymshark"}')

    assert result.kind is QueryKind.AUTHOR_FILTER
    assert result.author == "gymshark"


def test_author_filter_without_an_author_degrades_to_a_topic_list() -> None:
    """Filtering by nobody is not actionable; a semantic list at least tries."""
    result = _parse_classification('{"kind": "AUTHOR_FILTER", "author": null}')

    assert result.kind is QueryKind.LIST


def test_an_author_on_a_non_author_query_is_discarded() -> None:
    result = _parse_classification('{"kind": "LIST", "author": "gymshark"}')

    assert result.author is None


@pytest.mark.parametrize("content", ["not json at all", "", '{"kind": "NONSENSE"}'])
def test_unparseable_classification_falls_back_to_single(content: str) -> None:
    assert _parse_classification(content).kind is QueryKind.SINGLE


def test_a_named_collection_is_snapped_onto_the_vaults_own_spelling() -> None:
    result = _parse_classification(
        '{"kind": "LIST", "collection": "sales"}', ["Sales", "Fitness"]
    )

    assert result.collection == "Sales"


def test_a_collection_the_vault_does_not_have_is_dropped() -> None:
    """Better to fall through to semantic search than to filter on a shelf
    that cannot match anything."""
    result = _parse_classification(
        '{"kind": "LIST", "collection": "Cooking"}', ["Sales", "Fitness"]
    )

    assert result.collection is None


def test_tags_survive_a_fenced_reply() -> None:
    assert _parse_tag_list('```json\n["ai", "Agents"]\n```') == ["ai", "agents"]


def test_assignment_survives_a_fenced_reply_and_reuses_existing_casing() -> None:
    result = _parse_assignment(
        '```json\n{"collection": "ai", "subcollection": null}\n```', {"AI": []}
    )

    assert result.collection == "AI"


def test_unparseable_assignment_is_uncategorized_not_a_guess() -> None:
    assert _parse_assignment("who knows", {"AI": []}).collection == UNCATEGORIZED


def test_summary_sources_are_labelled_with_their_creator() -> None:
    labelled = _format_source(
        SummarySource(caption="squat cues", author_handle="gymshark", author_name="Gymshark")
    )

    assert "gymshark" in labelled
    assert "squat cues" in labelled


def test_an_unknown_creator_is_named_as_unknown() -> None:
    """Left blank, the model could read the caption as the previous author's."""
    assert "unknown" in _format_source(SummarySource(caption="squat cues"))


# --- the reranker's reply ----------------------------------------------------
#
# Two failures that mean opposite things meet in this parser. `[]` is the
# model saying it read the shortlist and none of it answers -- the one thing
# a similarity threshold could never say. A reply that does not parse is the
# model failing to answer at all, and reading that as "none of them" would
# turn every bad reply into a confident "nothing matched" for a user whose
# vault does hold the answer.


def test_kept_numbers_are_one_based_as_the_prompt_presents_them() -> None:
    assert _parse_kept_indices("[2, 1]", 3) == [1, 0]


def test_an_empty_verdict_is_kept_as_a_verdict() -> None:
    """"I read these and none of them answer" has to survive parsing intact."""
    assert _parse_kept_indices("[]", 3) == []


@pytest.mark.parametrize(
    "content",
    [
        "who knows",
        "",
        '{"kept": [1]}',
    ],
)
def test_an_unusable_reply_keeps_every_candidate(content: str) -> None:
    """Degrades to the order similarity already put them in — which is what
    the vault answered from before there was a reranker at all."""
    assert _parse_kept_indices(content, 3) == [0, 1, 2]


def test_a_reply_naming_no_real_candidate_keeps_every_candidate() -> None:
    """Answering with numbers that are not on offer is a broken reply, not a
    considered rejection, and must not be read as one."""
    assert _parse_kept_indices("[7, 9]", 3) == [0, 1, 2]


def test_out_of_range_and_repeated_numbers_are_dropped() -> None:
    """The two ways a list of numbers goes wrong. Either would otherwise
    reach the user as a duplicated or a non-existent reel."""
    assert _parse_kept_indices("[1, 1, 4, 2, 0]", 3) == [0, 1]


def test_the_reranker_sees_its_candidates_numbered_from_one() -> None:
    """It answers *about* these reels rather than from them, so it needs a
    way to name one."""
    block = _question_with_numbered_sources(
        "which is a snack",
        [SummarySource(caption="Texas toast steak sandwich"), SummarySource(caption="Chakna")],
    )

    assert "1. " in block
    assert "2. " in block
    assert "which is a snack" in block
