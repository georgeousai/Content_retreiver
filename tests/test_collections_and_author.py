"""Seam-level tests for collection assignment and author capture."""

from __future__ import annotations

from reel_vault.models import (
    UNCATEGORIZED,
    CollectionAssignment,
    ExtractedPost,
    NeedsCollectionChoice,
    Saved,
)
from reel_vault.search import embedding_text
from tests.conftest import make_vault
from tests.fakes import FakeCollectionAssigner, FakeEmbedder, InMemoryReelStore

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
        },
        assignments={"a caption": CollectionAssignment(collection="AI")},
    )

    result = vault.save_reel(URL)

    assert isinstance(result, Saved)
    assert result.reel.author_handle == "bashi_fuirkashi"
    assert result.reel.author_name == "Bashiri Smith"


def test_author_is_absent_when_extraction_does_not_expose_it() -> None:
    vault = make_vault(
        captions={URL: "a caption with no author"},
        assignments={"a caption with no author": CollectionAssignment(collection="AI")},
    )

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


def test_unsure_assignment_pauses_the_save_and_asks_instead_of_guessing() -> None:
    """An Uncategorized verdict from the assigner means 'I'm not confident' —
    the save must pause rather than silently writing an unrelated guess."""
    store = InMemoryReelStore()
    vault = make_vault(
        captions={URL: "totally unclassifiable"},
        tags_by_caption={"totally unclassifiable": ["misc"]},
        assignments={"totally unclassifiable": CollectionAssignment(collection=UNCATEGORIZED)},
        store=store,
    )

    result = vault.save_reel(URL)

    assert isinstance(result, NeedsCollectionChoice)
    assert result.url == "https://instagram.com/p/ABC"
    assert result.caption == "totally unclassifiable"
    assert result.tags == ["misc"]
    # Nothing was written — the row doesn't exist until the user decides.
    assert store.find_by_url(URL) is None


def test_assign_collection_finishes_the_save_and_writes_the_row() -> None:
    store = InMemoryReelStore()
    vault = make_vault(
        captions={URL: "totally unclassifiable"},
        assignments={"totally unclassifiable": CollectionAssignment(collection=UNCATEGORIZED)},
        store=store,
    )

    pending = vault.save_reel(URL)
    assert isinstance(pending, NeedsCollectionChoice)

    result = vault.assign_collection(pending, collection="Random Musings")

    assert isinstance(result, Saved)
    assert result.reel.collection == "Random Musings"
    assert result.reel.subcollection is None
    assert result.reel.caption == "totally unclassifiable"
    assert store.find_by_url("https://instagram.com/p/ABC") is not None


def test_a_reel_placed_by_hand_is_embedded_with_the_collection_it_was_given() -> None:
    """A reel is embedded together with the shelf it sits on, so a save that
    paused to ask where it belongs cannot embed until the user answers — and
    must then embed with the answer, not with the caption alone."""
    embedder = FakeEmbedder()
    vault = make_vault(
        captions={URL: "totally unclassifiable"},
        tags_by_caption={"totally unclassifiable": ["misc"]},
        assignments={"totally unclassifiable": CollectionAssignment(collection=UNCATEGORIZED)},
        embedder=embedder,
    )
    pending = vault.save_reel(URL)
    assert isinstance(pending, NeedsCollectionChoice)

    result = vault.assign_collection(
        pending, collection="Random Musings", subcollection="Half Thoughts"
    )

    assert isinstance(result, Saved)
    assert result.reel.embedding == embedder.embed(
        embedding_text(
            "totally unclassifiable", ["misc"], "Random Musings", "Half Thoughts"
        )
    )
    assert result.reel.embedding != embedder.embed("totally unclassifiable")


def test_assign_collection_accepts_a_subcollection() -> None:
    vault = make_vault(
        captions={URL: "totally unclassifiable"},
        assignments={"totally unclassifiable": CollectionAssignment(collection=UNCATEGORIZED)},
    )
    pending = vault.save_reel(URL)
    assert isinstance(pending, NeedsCollectionChoice)

    result = vault.assign_collection(pending, collection="AI", subcollection="Agents")

    assert isinstance(result, Saved)
    assert result.reel.collection == "AI"
    assert result.reel.subcollection == "Agents"
