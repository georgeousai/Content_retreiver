"""Seam-level tests for collection assignment and author capture."""

from __future__ import annotations

from reel_vault.models import (
    UNCATEGORIZED,
    CollectionAssignment,
    ExtractedPost,
    Saved,
)
from tests.conftest import make_vault
from tests.fakes import FakeCollectionAssigner, InMemoryReelStore

URL = "https://instagram.com/reel/ABC"


def test_saved_reel_carries_its_assigned_collection_and_subcollection() -> None:
    vault = make_vault(
        captions={URL: "a caption about transformers"},
        assignments={
            "a caption about transformers": CollectionAssignment(
                collection="AI", subcollection="Model Architectures"
            )
        },
    )

    result = vault.save_reel(URL)

    assert isinstance(result, Saved)
    assert result.reel.collection == "AI"
    assert result.reel.subcollection == "Model Architectures"


def test_subcollection_is_optional() -> None:
    vault = make_vault(
        captions={URL: "a caption"},
        assignments={"a caption": CollectionAssignment(collection="AI")},
    )

    result = vault.save_reel(URL)

    assert isinstance(result, Saved)
    assert result.reel.collection == "AI"
    assert result.reel.subcollection is None


def test_assigner_is_offered_the_collections_already_in_the_vault() -> None:
    """The whole point of reuse-first: the assigner must see what exists."""
    store = InMemoryReelStore()
    assigner = FakeCollectionAssigner(
        assignments={
            "first caption": CollectionAssignment(collection="AI", subcollection="RAG"),
            "second caption": CollectionAssignment(collection="AI"),
        }
    )
    vault = make_vault(
        captions={
            URL: "first caption",
            "https://instagram.com/reel/DEF": "second caption",
        },
        collection_assigner=assigner,
        store=store,
    )

    vault.save_reel(URL)
    vault.save_reel("https://instagram.com/reel/DEF")

    # First save: vault was empty, so nothing to reuse.
    assert assigner.seen_known[0] == {}
    # Second save: the AI collection (and its RAG sub-collection) is offered.
    assert assigner.seen_known[1] == {"AI": ["RAG"]}


def test_author_handle_and_name_are_stored_from_extraction() -> None:
    vault = make_vault(
        captions={
            URL: ExtractedPost(
                caption="a caption",
                author_handle="bashi_fuirkashi",
                author_name="Bashiri Smith",
            )
        }
    )

    result = vault.save_reel(URL)

    assert isinstance(result, Saved)
    assert result.reel.author_handle == "bashi_fuirkashi"
    assert result.reel.author_name == "Bashiri Smith"


def test_author_is_absent_when_extraction_does_not_expose_it() -> None:
    vault = make_vault(captions={URL: "a caption with no author"})

    result = vault.save_reel(URL)

    assert isinstance(result, Saved)
    assert result.reel.author_handle is None
    assert result.reel.author_name is None


def test_manually_pasted_caption_is_still_assigned_a_collection() -> None:
    vault = make_vault(
        captions={URL: None},
        assignments={"pasted text": CollectionAssignment(collection="Cooking")},
    )

    result = vault.save_reel(URL, manual_caption="pasted text")

    assert isinstance(result, Saved)
    assert result.reel.collection == "Cooking"
    assert result.reel.author_handle is None


def test_unclassifiable_caption_falls_back_to_uncategorized() -> None:
    vault = make_vault(captions={URL: "totally unclassifiable"})

    result = vault.save_reel(URL)

    assert isinstance(result, Saved)
    assert result.reel.collection == UNCATEGORIZED
