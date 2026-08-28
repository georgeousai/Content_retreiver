from __future__ import annotations

from reel_vault.models import AlreadySaved, ExtractionFailed, Saved
from tests.conftest import make_vault
from tests.fakes import InMemoryReelStore


def test_saving_a_new_reel_produces_a_tagged_embedded_record() -> None:
    vault = make_vault(
        captions={"https://instagram.com/reel/ABC": "A caption about transformers"},
        tags_by_caption={"A caption about transformers": ["ai", "transformers"]},
    )

    result = vault.save_reel("https://instagram.com/reel/ABC")

    assert isinstance(result, Saved)
    assert result.reel.caption == "A caption about transformers"
    assert result.reel.tags == ["ai", "transformers"]
    assert len(result.reel.embedding) > 0
    assert result.reel.url == "https://instagram.com/p/ABC"


def test_saving_a_duplicate_url_returns_existing_record_without_new_row() -> None:
    shared_store = InMemoryReelStore()
    vault = make_vault(
        captions={"https://instagram.com/reel/ABC": "first caption"},
        store=shared_store,
    )

    first = vault.save_reel("https://instagram.com/reel/ABC")
    assert isinstance(first, Saved)

    second = vault.save_reel("https://www.instagram.com/reel/ABC/?igsh=xyz")

    assert isinstance(second, AlreadySaved)
    assert second.reel.tags == first.reel.tags
    assert second.reel.url == first.reel.url


def test_extraction_failure_returns_extraction_failed_without_saving() -> None:
    shared_store_vault = make_vault(captions={"https://instagram.com/reel/DEAD": None})

    result = shared_store_vault.save_reel("https://instagram.com/reel/DEAD")

    assert isinstance(result, ExtractionFailed)
    assert result.url == "https://instagram.com/reel/DEAD"


def test_extraction_failure_on_empty_caption() -> None:
    vault = make_vault(captions={"https://instagram.com/reel/EMPTY": "   "})

    result = vault.save_reel("https://instagram.com/reel/EMPTY")

    assert isinstance(result, ExtractionFailed)


def test_manual_caption_flows_through_same_tagging_and_storage_path() -> None:
    vault = make_vault(
        captions={"https://instagram.com/reel/DEAD": None},
        tags_by_caption={"pasted caption text": ["manual"]},
    )

    first = vault.save_reel("https://instagram.com/reel/DEAD")
    assert isinstance(first, ExtractionFailed)

    result = vault.save_reel(
        "https://instagram.com/reel/DEAD", manual_caption="pasted caption text"
    )

    assert isinstance(result, Saved)
    assert result.reel.caption == "pasted caption text"
    assert result.reel.tags == ["manual"]


def test_losing_a_race_to_the_same_url_reports_already_saved() -> None:
    """Two bot processes (or a double-tap) can both pass the duplicate check
    before either writes. The one whose insert does nothing must not claim
    it saved the reel — observed live as two "Saved!" replies for one row.
    """
    store = InMemoryReelStore()
    vault = make_vault(
        captions={"https://instagram.com/reel/RACE": "a caption about ai"},
        store=store,
    )
    winner = vault.save_reel("https://instagram.com/reel/RACE")
    assert isinstance(winner, Saved)

    # The loser reached save() with its own record, the row already there.
    loser = vault._persist(winner.reel, thumbnail_url=None)

    assert isinstance(loser, AlreadySaved)
    assert loser.reel.url == winner.reel.url


def test_manual_caption_still_honors_duplicate_check() -> None:
    shared_store = InMemoryReelStore()
    vault = make_vault(captions={}, store=shared_store)

    vault.save_reel("https://instagram.com/reel/DUP", manual_caption="caption one")
    second = vault.save_reel("https://instagram.com/reel/DUP", manual_caption="caption two")

    assert isinstance(second, AlreadySaved)
    assert second.reel.caption == "caption one"
