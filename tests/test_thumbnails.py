"""Seam-level tests for capturing a reel's thumbnail as it is saved."""

from __future__ import annotations

from reel_vault.models import (
    UNCATEGORIZED,
    CollectionAssignment,
    ExtractedPost,
    NeedsCollectionChoice,
    Saved,
)
from tests.conftest import make_vault
from tests.fakes import FakeThumbnailStore

URL = "https://instagram.com/reel/ABC"
POST = ExtractedPost(caption="a caption about ai", thumbnail_url="https://cdn/thumb.jpg")


def test_saving_captures_a_durable_reference_to_the_thumbnail() -> None:
    thumbnails = FakeThumbnailStore()
    vault = make_vault(captions={URL: POST}, thumbnail_store=thumbnails)

    result = vault.save_reel(URL)

    assert isinstance(result, Saved)
    assert result.reel.thumbnail_ref == "file-id-for:https://cdn/thumb.jpg"
    # The expiring CDN URL is what we were handed; it is not what we keep.
    assert result.reel.thumbnail_ref != POST.thumbnail_url
    assert thumbnails.calls == ["https://cdn/thumb.jpg"]


def test_a_post_without_a_thumbnail_saves_normally() -> None:
    thumbnails = FakeThumbnailStore()
    vault = make_vault(
        captions={URL: ExtractedPost(caption="a caption about ai")},
        thumbnail_store=thumbnails,
    )

    result = vault.save_reel(URL)

    assert isinstance(result, Saved)
    assert result.reel.thumbnail_ref is None
    assert thumbnails.calls == []


def test_a_failing_thumbnail_upload_does_not_lose_the_reel() -> None:
    """A picture is a nicety; the saved reel is the point."""
    thumbnails = FakeThumbnailStore(fail=True)
    vault = make_vault(captions={URL: POST}, thumbnail_store=thumbnails)

    result = vault.save_reel(URL)

    assert isinstance(result, Saved)
    assert result.reel.thumbnail_ref is None
    assert result.reel.caption == "a caption about ai"


def test_pausing_for_a_collection_choice_does_not_re_upload_the_thumbnail() -> None:
    thumbnails = FakeThumbnailStore()
    vault = make_vault(
        captions={URL: POST},
        assignments={"a caption about ai": CollectionAssignment(collection=UNCATEGORIZED)},
        thumbnail_store=thumbnails,
    )

    pending = vault.save_reel(URL)
    assert isinstance(pending, NeedsCollectionChoice)
    assert pending.thumbnail_ref == "file-id-for:https://cdn/thumb.jpg"

    result = vault.assign_collection(pending, collection="AI")

    assert result.reel.thumbnail_ref == "file-id-for:https://cdn/thumb.jpg"
    assert thumbnails.calls == ["https://cdn/thumb.jpg"], "uploaded once, not twice"


def test_a_manually_pasted_caption_still_saves_without_a_thumbnail() -> None:
    thumbnails = FakeThumbnailStore()
    vault = make_vault(captions={URL: None}, thumbnail_store=thumbnails)

    result = vault.save_reel(URL, manual_caption="pasted text")

    assert isinstance(result, Saved)
    assert result.reel.thumbnail_ref is None
