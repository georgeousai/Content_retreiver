"""Unit tests for the Groq adapters' reply parsing.

No network: these exercise the pure parsing functions. They exist because an
unparsed reply is never an error the user sees — it is silently the wrong
answer shape, which is the worst way for this to fail.
"""

from __future__ import annotations

import pytest

from reel_vault.adapters.groq_llm import (
    _format_source,
    _parse_assignment,
    _parse_classification,
    _parse_tag_list,
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
