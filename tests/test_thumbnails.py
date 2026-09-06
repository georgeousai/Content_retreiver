"""Seam-level tests for a saved reel's picture.

Only the transport layer can mint a durable reference (Telegram hands back a
non-expiring file_id for any photo it has seen), so the vault's half is:
surface the extracted URL on the save result, and record the reference it is
handed afterwards. The minting itself is covered in `test_bot.py`.
"""

from __future__ import annotations

from dataclasses import replace

from reel_vault.models import (
    UNCATEGORIZED,
    CollectionAssignment,
    ExtractedPost,
    NeedsCollectionChoice,
    Saved,
)
from tests.conftest import make_vault
from tests.fakes import InMemoryReelStore

URL = "https://instagram.com/reel/ABC"
POST = ExtractedPost(caption="a caption about ai", thumbnail_url="https://cdn/thumb.jpg")


def test_saving_surfaces_the_thumbnail_url_to_upload() -> None:
    vault = make_vault(captions={URL: POST})

    result = vault.save_reel(URL)

    assert isinstance(result, Saved)
    assert result.thumbnail_url == "https://cdn/thumb.jpg"
    # Nothing durable exists yet — the transport layer has not been asked.
    assert result.reel.thumbnail_ref is None


def test_a_post_without_a_thumbnail_saves_normally() -> None:
    vault = make_vault(captions={URL: ExtractedPost(caption="a caption about ai")})

    result = vault.save_reel(URL)

    assert isinstance(result, Saved)
    assert result.thumbnail_url is None
    assert result.reel.thumbnail_ref is None


def test_attaching_a_thumbnail_records_it_against_the_saved_reel() -> None:
    store = InMemoryReelStore()
    vault = make_vault(captions={URL: POST}, store=store)
    assert isinstance(vault.save_reel(URL), Saved)

    vault.attach_thumbnail(URL, "telegram-file-id")

    saved = store.find_by_url("https://instagram.com/p/ABC")
    assert saved is not None
    assert saved.thumbnail_ref == "telegram-file-id"
    # The expiring CDN URL is never what we keep.
    assert saved.thumbnail_ref != POST.thumbnail_url


def _paused_save(store: InMemoryReelStore | None = None):
    vault = make_vault(
        captions={URL: POST},
        assignments={"a caption about ai": CollectionAssignment(collection=UNCATEGORIZED)},
        store=store,
    )
    pending = vault.save_reel(URL)
    assert isinstance(pending, NeedsCollectionChoice)
    return vault, pending


def test_pausing_for_a_collection_choice_carries_the_thumbnail_url_through() -> None:
    vault, pending = _paused_save()
    assert pending.thumbnail_url == "https://cdn/thumb.jpg"

    result = vault.assign_collection(pending, collection="AI")

    assert isinstance(result, Saved)
    assert result.thumbnail_url == "https://cdn/thumb.jpg"


def test_a_reference_minted_before_the_pause_is_what_the_finished_save_keeps() -> None:
    """The transport can mint the durable reference while it asks the
    question — and should, because the extracted URL expires and this save
    waits on a person. Handed one, the finished reel carries it, and the
    caller is not asked to upload anything a second time."""
    store = InMemoryReelStore()
    vault, pending = _paused_save(store)

    result = vault.assign_collection(
        replace(pending, thumbnail_ref="telegram-file-id"), collection="AI"
    )

    assert isinstance(result, Saved)
    assert result.reel.thumbnail_ref == "telegram-file-id"
    # Nothing left for the caller to mint, so it is not handed the dead URL.
    assert result.thumbnail_url is None
    saved = store.find_by_url("https://instagram.com/p/ABC")
    assert saved is not None
    assert saved.thumbnail_ref == "telegram-file-id"


def test_a_manually_pasted_caption_has_no_thumbnail_to_upload() -> None:
    vault = make_vault(captions={URL: None})

    result = vault.save_reel(URL, manual_caption="pasted text")

    assert isinstance(result, Saved)
    assert result.thumbnail_url is None
