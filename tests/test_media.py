"""Seam-level tests for what a reel's video adds to it.

The vault's half of the media pipeline is: be handed what a video contained,
condense it, store both halves, and re-embed so the new words are reachable.
Downloading, transcribing and reading frames are adapter concerns and are
faked here, exactly as caption fetching and tagging already are.
"""

from __future__ import annotations

import pytest

from reel_vault.models import (
    ExtractedPost,
    MediaExtraction,
    ProcessingStatus,
    Saved,
    SingleItemAnswer,
)
from tests.conftest import make_vault
from tests.fakes import FakeCondenser, FakeMediaExtractor, InMemoryReelStore

URL = "https://instagram.com/reel/ABC"
SAVED_URL = "https://instagram.com/p/ABC"
# The shape that motivates the whole pipeline: the caption withholds the
# content and the video carries it.
BAIT_CAPTION = "comment HABITS for my list"
TRANSCRIPT = "wake up at five\ncold shower every morning\njournal before your phone"
FRAMES = "on screen: 1. WAKE 5AM\non screen: 2. COLD SHOWER"


@pytest.fixture
def store() -> InMemoryReelStore:
    return InMemoryReelStore()


def _saved_vault(store: InMemoryReelStore, **overrides):
    vault = make_vault(
        captions={URL: ExtractedPost(caption=BAIT_CAPTION)}, store=store, **overrides
    )
    assert isinstance(vault.save_reel(URL), Saved)
    return vault


def test_a_new_reel_starts_out_awaiting_its_video(store: InMemoryReelStore) -> None:
    _saved_vault(store)

    saved = store.find_by_url(SAVED_URL)
    assert saved is not None
    assert saved.processing_status is ProcessingStatus.PENDING
    assert saved.transcript_raw == ""
    assert saved.transcript_summary == ""


def test_attaching_an_extraction_stores_the_raw_text_and_a_summary(
    store: InMemoryReelStore,
) -> None:
    condenser = FakeCondenser()
    vault = _saved_vault(store, condenser=condenser)

    vault.attach_media(
        URL, MediaExtraction(transcript=TRANSCRIPT, frame_analysis=FRAMES)
    )

    saved = store.find_by_url(SAVED_URL)
    assert saved is not None
    assert saved.processing_status is ProcessingStatus.DONE
    # Raw is kept verbatim: it exists so a poor summary can be redone without
    # re-downloading a video whose URL will have expired by then.
    assert saved.transcript_raw == TRANSCRIPT
    assert saved.frame_analysis_raw == FRAMES
    assert saved.transcript_summary == "summary of: wake up at five"
    assert saved.frame_analysis_summary == "summary of: on screen: 1. WAKE 5AM"


def test_only_the_summaries_are_ever_embedded(store: InMemoryReelStore) -> None:
    """The raw halves are storage, not search. Embedding a whole transcript
    would swamp the caption and the shelf the reel sits on."""
    vault = _saved_vault(store, condenser=FakeCondenser())
    embedder = vault._embedder  # the fake records every text it embedded

    vault.attach_media(
        URL, MediaExtraction(transcript=TRANSCRIPT, frame_analysis=FRAMES)
    )

    embedded = "\n".join(embedder.calls)
    assert "summary of: wake up at five" in embedded
    assert "cold shower every morning" not in embedded


def test_content_only_spoken_in_the_video_becomes_findable(
    store: InMemoryReelStore,
) -> None:
    """The ceiling this whole feature exists to lift: a caption that says
    nothing, and content only the audio carries."""
    vault = _saved_vault(store)
    assert vault.ask("journal").__class__.__name__ == "NoMatch"

    vault.attach_media(URL, MediaExtraction(transcript=TRANSCRIPT))

    answer = vault.ask("journal")
    assert isinstance(answer, SingleItemAnswer)
    assert answer.reel.url == SAVED_URL


def test_a_failed_extraction_is_recorded_without_disturbing_the_reel(
    store: InMemoryReelStore,
) -> None:
    vault = _saved_vault(store)
    before = store.find_by_url(SAVED_URL)
    assert before is not None

    vault.attach_media(URL, None)

    after = store.find_by_url(SAVED_URL)
    assert after is not None
    assert after.processing_status is ProcessingStatus.FAILED
    assert after.caption == before.caption
    assert after.collection == before.collection
    assert after.embedding == before.embedding
    assert after.transcript_raw == ""


def test_an_extraction_that_recovered_nothing_counts_as_a_failure(
    store: InMemoryReelStore,
) -> None:
    """An empty result is not a processed reel. Marking it done would claim
    the video was read and had nothing in it, which is not what happened."""
    vault = _saved_vault(store)

    vault.attach_media(URL, MediaExtraction(transcript="  ", frame_analysis=""))

    saved = store.find_by_url(SAVED_URL)
    assert saved is not None
    assert saved.processing_status is ProcessingStatus.FAILED


def test_attaching_media_to_an_unknown_reel_does_nothing(
    store: InMemoryReelStore,
) -> None:
    vault = _saved_vault(store)

    assert vault.attach_media("https://instagram.com/reel/NOPE", MediaExtraction("x")) is None


def test_reels_awaiting_their_video_are_listed_for_a_restart_to_pick_up(
    store: InMemoryReelStore,
) -> None:
    vault = _saved_vault(store)

    assert vault.resume_pending_media() == [SAVED_URL]

    vault.attach_media(URL, MediaExtraction(transcript=TRANSCRIPT))
    assert vault.resume_pending_media() == []


def test_a_failed_reel_is_not_retried_forever(store: InMemoryReelStore) -> None:
    """Left pending, a reel whose video has expired would be re-downloaded on
    every restart for as long as it exists."""
    vault = _saved_vault(store)

    vault.attach_media(URL, None)

    assert vault.resume_pending_media() == []


def test_processing_runs_the_extractor_and_stores_what_it_found(
    store: InMemoryReelStore,
) -> None:
    extractor = FakeMediaExtractor({SAVED_URL: MediaExtraction(transcript=TRANSCRIPT)})
    vault = _saved_vault(store, media_extractor=extractor, condenser=FakeCondenser())

    vault.process_media(URL)

    assert extractor.calls == [SAVED_URL]
    saved = store.find_by_url(SAVED_URL)
    assert saved is not None
    assert saved.processing_status is ProcessingStatus.DONE
    assert saved.transcript_raw == TRANSCRIPT


def test_an_extractor_that_raises_marks_the_reel_failed_rather_than_escaping(
    store: InMemoryReelStore,
) -> None:
    """This runs detached in the background, where an escaping exception is
    invisible and leaves the reel wedged on pending forever."""
    extractor = FakeMediaExtractor({SAVED_URL: RuntimeError("network died")})
    vault = _saved_vault(store, media_extractor=extractor)

    vault.process_media(URL)

    saved = store.find_by_url(SAVED_URL)
    assert saved is not None
    assert saved.processing_status is ProcessingStatus.FAILED


def test_moving_a_reel_keeps_the_transcript_it_had_earned(
    store: InMemoryReelStore,
) -> None:
    """A move re-embeds. Re-deriving that text from the caption alone would
    silently drop the video's words and make the reel unfindable by them —
    the same trap that once left a moved reel findable under its old shelf.
    """
    vault = _saved_vault(store, condenser=FakeCondenser())
    vault.attach_media(URL, MediaExtraction(transcript=TRANSCRIPT))
    assert isinstance(vault.ask("wake"), SingleItemAnswer)

    vault.refile(URL, collection="Personal Growth", subcollection="Routines")

    moved = store.find_by_url(SAVED_URL)
    assert moved is not None
    assert moved.transcript_summary == "summary of: wake up at five"
    assert isinstance(vault.ask("wake"), SingleItemAnswer)


def test_undoing_a_move_keeps_the_transcript_too(store: InMemoryReelStore) -> None:
    vault = _saved_vault(store, condenser=FakeCondenser())
    vault.attach_media(URL, MediaExtraction(transcript=TRANSCRIPT))
    vault.refile(URL, collection="Personal Growth")

    vault.undo_last_move(URL)

    assert isinstance(vault.ask("wake"), SingleItemAnswer)


def test_without_a_condenser_the_raw_text_stands_in_for_its_summary(
    store: InMemoryReelStore,
) -> None:
    """Searching a whole transcript is worse than searching a tight summary,
    and far better than losing the content."""
    vault = _saved_vault(store)

    vault.attach_media(URL, MediaExtraction(transcript=TRANSCRIPT))

    saved = store.find_by_url(SAVED_URL)
    assert saved is not None
    assert saved.transcript_summary == TRANSCRIPT
