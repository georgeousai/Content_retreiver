"""Placing a reel using where comparable reels actually went, and taking a
move back.

The collection names alone say what shelves exist, never what goes on them.
That gap is how "Five Year Journey #fyp #smallbusiness" landed in Personal
Growth > Journey: a sub-collection called Journey already existed, the word
matched, and nothing told the classifier that reels of that kind had been
going somewhere else.
"""

from __future__ import annotations

from reel_vault.models import CollectionAssignment, Saved
from tests.conftest import make_vault
from tests.fakes import FakeCollectionAssigner, InMemoryReelStore

FIRST = "https://instagram.com/p/first"
SECOND = "https://instagram.com/p/second"


def _vault(**overrides):
    assigner = FakeCollectionAssigner(
        assignments={
            "deadlift form breakdown": CollectionAssignment(collection="Fitness"),
            "deadlift technique tips": CollectionAssignment(collection="Fitness"),
        }
    )
    store = InMemoryReelStore()
    vault = make_vault(
        captions={
            FIRST: "deadlift form breakdown",
            SECOND: "deadlift technique tips",
        },
        collection_assigner=assigner,
        store=store,
        **overrides,
    )
    return vault, store, assigner


# --- what the classifier is shown ------------------------------------------


def test_the_assigner_is_shown_where_similar_reels_were_filed() -> None:
    vault, _, assigner = _vault()
    assert isinstance(vault.save_reel(FIRST), Saved)

    assert isinstance(vault.save_reel(SECOND), Saved)

    neighbours = assigner.seen_neighbours[-1]
    assert [n.caption for n in neighbours] == ["deadlift form breakdown"]
    assert neighbours[0].collection == "Fitness"


def test_the_first_reel_saved_is_placed_with_no_neighbours_at_all() -> None:
    vault, _, assigner = _vault()

    assert isinstance(vault.save_reel(FIRST), Saved)

    assert assigner.seen_neighbours[-1] == []


def test_a_reel_the_user_moved_is_marked_as_their_decision() -> None:
    """A placement this classifier made is not evidence of anything; a
    placement the user made is. Without the distinction, one bad guess
    becomes the precedent for every reel that resembles it."""
    vault, _, assigner = _vault()
    assert isinstance(vault.save_reel(FIRST), Saved)
    vault.refile(FIRST, collection="Strength Training")

    assert isinstance(vault.save_reel(SECOND), Saved)

    neighbour = assigner.seen_neighbours[-1][0]
    assert neighbour.collection == "Strength Training"
    assert neighbour.user_placed is True


def test_a_reel_the_classifier_placed_is_not_marked_as_the_users() -> None:
    vault, _, assigner = _vault()
    assert isinstance(vault.save_reel(FIRST), Saved)

    assert isinstance(vault.save_reel(SECOND), Saved)

    assert assigner.seen_neighbours[-1][0].user_placed is False


def test_answering_the_unsure_prompt_counts_as_the_users_decision() -> None:
    """Being asked and answering is as much a human placement as correcting
    one afterwards."""
    from reel_vault.models import UNCATEGORIZED, NeedsCollectionChoice

    assigner = FakeCollectionAssigner(
        assignments={"totally unclassifiable": CollectionAssignment(collection=UNCATEGORIZED)}
    )
    store = InMemoryReelStore()
    vault = make_vault(
        captions={FIRST: "totally unclassifiable"},
        collection_assigner=assigner,
        store=store,
    )
    pending = vault.save_reel(FIRST)
    assert isinstance(pending, NeedsCollectionChoice)

    result = vault.assign_collection(pending, collection="Odds And Ends")

    assert isinstance(result, Saved)
    assert result.reel.user_placed is True


def test_captions_are_compared_to_captions_not_to_shelf_names() -> None:
    """A reel is embedded together with its collection for retrieval. Reusing
    that embedding here would let a shelf attract reels merely for sharing its
    vocabulary — the reuse bias this lookup exists to counter."""
    vault, store, _ = _vault()
    assert isinstance(vault.save_reel(FIRST), Saved)

    saved = store.find_by_url(FIRST)
    assert saved is not None
    assert saved.caption_embedding
    assert saved.caption_embedding != saved.embedding


# --- taking a move back -----------------------------------------------------


def test_undo_puts_a_moved_reel_back() -> None:
    vault, store, _ = _vault()
    assert isinstance(vault.save_reel(FIRST), Saved)
    vault.refile(FIRST, collection="Strength Training", subcollection="Deadlift")

    restored = vault.undo_last_move(FIRST)

    assert restored is not None
    assert restored.collection == "Fitness"
    assert restored.subcollection is None


def test_undo_re_embeds_for_the_shelf_it_returns_to() -> None:
    vault, store, _ = _vault()
    assert isinstance(vault.save_reel(FIRST), Saved)
    before = store.find_by_url(FIRST)
    assert before is not None
    vault.refile(FIRST, collection="Strength Training")

    restored = vault.undo_last_move(FIRST)

    assert restored is not None
    assert restored.embedding == before.embedding


def test_undo_also_takes_back_the_users_authorship_of_the_placement() -> None:
    """Reversing a move must not leave a placement claiming a person chose
    it — otherwise an undone mistake would go on teaching the classifier."""
    vault, store, _ = _vault()
    assert isinstance(vault.save_reel(FIRST), Saved)
    vault.refile(FIRST, collection="Strength Training")

    restored = vault.undo_last_move(FIRST)

    assert restored is not None
    assert restored.user_placed is False


def test_undoing_a_reel_that_was_never_moved_does_nothing() -> None:
    vault, _, _ = _vault()
    assert isinstance(vault.save_reel(FIRST), Saved)

    assert vault.undo_last_move(FIRST) is None


def test_undo_goes_back_one_move_at_a_time() -> None:
    vault, _, _ = _vault()
    assert isinstance(vault.save_reel(FIRST), Saved)
    vault.refile(FIRST, collection="Strength Training")
    vault.refile(FIRST, collection="Powerlifting")

    assert (first := vault.undo_last_move(FIRST)) is not None
    assert first.collection == "Strength Training"
    assert (second := vault.undo_last_move(FIRST)) is not None
    assert second.collection == "Fitness"
    assert vault.undo_last_move(FIRST) is None


def test_undoing_a_reel_the_vault_does_not_have_does_nothing() -> None:
    vault, _, _ = _vault()

    assert vault.undo_last_move("https://instagram.com/p/nothing") is None


def test_captions_too_unlike_this_one_are_not_offered_as_precedent() -> None:
    """A genuinely novel reel has no useful neighbours. Handing the classifier
    the five least-unrelated reels anyway presents noise in the same shape as
    evidence, which is worse than saying nothing at all."""
    assigner = FakeCollectionAssigner(
        assignments={
            "deadlift form breakdown": CollectionAssignment(collection="Fitness"),
            "sourdough starter troubleshooting": CollectionAssignment(collection="Cooking"),
        }
    )
    vault = make_vault(
        captions={
            FIRST: "deadlift form breakdown",
            SECOND: "sourdough starter troubleshooting",
        },
        collection_assigner=assigner,
        store=InMemoryReelStore(),
    )
    assert isinstance(vault.save_reel(FIRST), Saved)

    assert isinstance(vault.save_reel(SECOND), Saved)

    assert assigner.seen_neighbours[-1] == []
