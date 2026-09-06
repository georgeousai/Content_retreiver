"""How the video-reading work gets off the path that answers the user, and
what happens to it when the process restarts underneath it."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from reel_vault.adapters.media import VideoMediaExtractor
from reel_vault.bot import ReelVaultBot
from reel_vault.models import MediaExtraction, ProcessingStatus
from tests.conftest import make_vault
from tests.fakes import FakeMediaExtractor, InMemoryReelStore

URL = "https://instagram.com/reel/ABC"
SAVED_URL = "https://instagram.com/p/ABC"


def _make_message(text: str, chat_id: int = 1) -> MagicMock:
    message = MagicMock()
    message.text = text
    message.chat_id = chat_id
    message.reply_text = AsyncMock()
    message.reply_photo = AsyncMock()
    message.reply_to_message = None
    return message


def _make_update(message: MagicMock, chat_id: int = 1) -> MagicMock:
    update = MagicMock()
    update.effective_message = message
    update.effective_chat.id = chat_id
    return update


@pytest.fixture
def store() -> InMemoryReelStore:
    return InMemoryReelStore()


def _bot(store: InMemoryReelStore, **overrides) -> ReelVaultBot:
    vault = make_vault(captions={URL: "comment HABITS for my list"}, store=store, **overrides)
    return ReelVaultBot(vault, token="123:fake-token-for-tests")


async def _drain(bot: ReelVaultBot) -> None:
    """Run the worker until the queue is empty, the way the real one runs
    forever alongside the polling loop."""
    worker = asyncio.create_task(bot._read_videos())
    await bot._media_queue.join()
    worker.cancel()


async def test_saving_a_reel_queues_its_video_without_waiting_for_it(
    store: InMemoryReelStore,
) -> None:
    """The confirmation is sent from the same call that queues the work, so a
    save stays as fast as it is today no matter how slow a video is."""
    extractor = FakeMediaExtractor({SAVED_URL: MediaExtraction(transcript="wake at five")})
    bot = _bot(store, media_extractor=extractor)

    await bot._on_message(_make_update(_make_message(URL)), MagicMock())

    assert bot._media_queue.qsize() == 1
    # Nothing has been read yet — the reply went out first.
    assert extractor.calls == []


async def test_the_queued_video_is_read_and_stored(store: InMemoryReelStore) -> None:
    extractor = FakeMediaExtractor({SAVED_URL: MediaExtraction(transcript="wake at five")})
    bot = _bot(store, media_extractor=extractor)
    await bot._on_message(_make_update(_make_message(URL)), MagicMock())

    await _drain(bot)

    saved = store.find_by_url(SAVED_URL)
    assert saved is not None
    assert saved.transcript_raw == "wake at five"
    assert saved.processing_status is ProcessingStatus.DONE


async def test_re_sharing_a_saved_reel_does_not_queue_it_again(
    store: InMemoryReelStore,
) -> None:
    bot = _bot(store, media_extractor=FakeMediaExtractor())
    await bot._on_message(_make_update(_make_message(URL)), MagicMock())
    bot._media_queue.get_nowait()

    await bot._on_message(_make_update(_make_message(URL)), MagicMock())

    assert bot._media_queue.qsize() == 0


async def test_a_restart_picks_up_the_reel_it_was_reading(
    store: InMemoryReelStore,
) -> None:
    """The queue lives only in the process. Without this, a restart mid-job
    leaves a reel permanently and silently without its transcript."""
    interrupted = _bot(store, media_extractor=FakeMediaExtractor())
    await interrupted._on_message(_make_update(_make_message(URL)), MagicMock())
    # The process dies here: the reel is saved and still pending.

    restarted = _bot(store, media_extractor=FakeMediaExtractor())
    await restarted._on_start(MagicMock())

    assert restarted._media_queue.qsize() == 1
    restarted._media_worker.cancel()


async def test_a_restart_leaves_already_read_reels_alone(
    store: InMemoryReelStore,
) -> None:
    extractor = FakeMediaExtractor({SAVED_URL: MediaExtraction(transcript="wake at five")})
    bot = _bot(store, media_extractor=extractor)
    await bot._on_message(_make_update(_make_message(URL)), MagicMock())
    await _drain(bot)

    restarted = _bot(store, media_extractor=extractor)
    await restarted._on_start(MagicMock())

    assert restarted._media_queue.qsize() == 0
    restarted._media_worker.cancel()


async def test_one_reel_failing_does_not_stop_the_worker(
    store: InMemoryReelStore,
) -> None:
    """A worker that dies on the first bad video is every later reel without
    a transcript, with nothing to say anything stopped."""
    bot = _bot(store, media_extractor=FakeMediaExtractor())
    bot._vault.process_media = MagicMock(side_effect=[RuntimeError("boom"), None])
    bot._queue_media("first")
    bot._queue_media("second")

    await _drain(bot)

    assert bot._vault.process_media.call_count == 2


class _StubDownloader:
    def __init__(self, fails: bool = False) -> None:
        self.fails = fails
        self.downloaded: Path | None = None

    def download(self, url: str, into: Path) -> Path | None:
        if self.fails:
            return None
        self.downloaded = into / "video.mp4"
        self.downloaded.write_bytes(b"not really a video")
        return self.downloaded


class _StubTranscriber:
    def __init__(self, text: str = "spoken words", raises: bool = False) -> None:
        self.text = text
        self.raises = raises

    def transcribe(self, media_path: Path) -> str:
        if self.raises:
            raise RuntimeError("transcription died")
        return self.text


class _StubSampler:
    def __init__(self, frames: list[bytes] | None = None, raises: bool = False) -> None:
        self.frames = frames if frames is not None else [b"jpeg"]
        self.raises = raises

    def sample(self, media_path: Path, max_frames: int) -> list[bytes]:
        if self.raises:
            raise RuntimeError("decoder died")
        return self.frames


class _StubAnalyzer:
    def __init__(self, text: str = "on screen: WAKE 5AM", raises: bool = False) -> None:
        self.text = text
        self.raises = raises

    def analyze(self, frames: list[bytes]) -> str:
        if self.raises:
            raise RuntimeError("vision died")
        return self.text


def _extractor(**parts) -> VideoMediaExtractor:
    defaults = {
        "downloader": _StubDownloader(),
        "transcriber": _StubTranscriber(),
        "frame_sampler": _StubSampler(),
        "frame_analyzer": _StubAnalyzer(),
    }
    return VideoMediaExtractor(**{**defaults, **parts})


def test_the_downloaded_video_is_deleted_after_it_is_read() -> None:
    """Disk must not grow with the size of the vault — the "no stored media"
    decision survives because the file never outlives the call."""
    downloader = _StubDownloader()

    _extractor(downloader=downloader).extract(URL)

    assert downloader.downloaded is not None
    assert not downloader.downloaded.exists()


def test_the_downloaded_video_is_deleted_even_when_reading_it_blows_up() -> None:
    downloader = _StubDownloader()

    _extractor(
        downloader=downloader,
        transcriber=_StubTranscriber(raises=True),
        frame_analyzer=_StubAnalyzer(raises=True),
    ).extract(URL)

    assert downloader.downloaded is not None
    assert not downloader.downloaded.exists()


def test_audio_and_frames_fail_independently() -> None:
    """A reel whose speech transcribed cleanly but whose frames could not be
    read is still worth far more than its caption alone."""
    result = _extractor(frame_analyzer=_StubAnalyzer(raises=True)).extract(URL)

    assert result is not None
    assert result.transcript == "spoken words"
    assert result.frame_analysis == ""


def test_a_transcription_failure_keeps_what_the_frames_showed() -> None:
    result = _extractor(transcriber=_StubTranscriber(raises=True)).extract(URL)

    assert result is not None
    assert result.transcript == ""
    assert result.frame_analysis == "on screen: WAKE 5AM"


def test_a_download_failure_reports_nothing_rather_than_raising() -> None:
    assert _extractor(downloader=_StubDownloader(fails=True)).extract(URL) is None


def test_a_video_nothing_could_be_read_from_reports_nothing() -> None:
    result = _extractor(
        transcriber=_StubTranscriber(text="   "), frame_analyzer=_StubAnalyzer(text="")
    ).extract(URL)

    assert result is None


def test_frames_are_not_analyzed_when_none_could_be_sampled() -> None:
    analyzer = _StubAnalyzer(raises=True)

    result = _extractor(frame_sampler=_StubSampler(frames=[]), frame_analyzer=analyzer).extract(URL)

    assert result is not None
    assert result.frame_analysis == ""


def test_an_extractor_with_no_analyzer_says_the_frames_went_unread() -> None:
    """A do-nothing analyzer returning "" made an unset VISION_API_KEY — a
    forgotten line in an .env — look exactly like a video with no text on
    screen. Absent is now absent, and the result says so."""
    result = _extractor(frame_analyzer=None).extract(URL)

    assert result is not None
    assert result.transcript == "spoken words"
    assert result.frame_analysis == ""
    assert result.frames_read is False


def test_an_analyzer_that_read_nothing_still_counts_as_having_looked() -> None:
    result = _extractor(frame_analyzer=_StubAnalyzer(text="")).extract(URL)

    assert result is not None
    assert result.frames_read is True


def test_an_analyzer_that_raised_did_not_read_the_frames() -> None:
    """Found in the live vault: a reel with a full transcript, no frame text,
    and status DONE. The vision call had failed -- a rate limit, during a
    burst of saves -- and `frames_read` was True because an analyzer
    *existed*. "Is one configured" and "did it answer" are different
    questions, and only the second one says whether the frames were read.

    The distinction is the whole reason `FRAMES_UNREAD` exists: with it a
    later pass can find this reel and finish it; without it the reel is
    indistinguishable from one whose video had nothing on screen.
    """
    result = _extractor(frame_analyzer=_StubAnalyzer(raises=True)).extract(URL)

    assert result is not None
    assert result.transcript == "spoken words"
    assert result.frame_analysis == ""
    assert result.frames_read is False


def test_a_sampler_that_raised_did_not_read_the_frames_either() -> None:
    """Same principle one step earlier. A video whose frames could not be
    decoded has not had them read; that is not knowledge that there was
    nothing on them."""
    result = _extractor(frame_sampler=_StubSampler(raises=True)).extract(URL)

    assert result is not None
    assert result.transcript == "spoken words"
    assert result.frames_read is False


def test_a_sampler_that_found_no_frames_still_counts_as_having_looked() -> None:
    """The line between unread and empty. No frames came back, so there is
    nothing the analyzer could have read -- that is knowing the answer, not
    failing to get one, and it must not be filed for a retry that would find
    the same nothing."""
    result = _extractor(frame_sampler=_StubSampler(frames=[])).extract(URL)

    assert result is not None
    assert result.frames_read is True


def test_frames_are_not_sampled_at_all_when_there_is_nothing_to_read_them() -> None:
    """No point decoding a video's frames into memory for an analyzer that
    does not exist."""
    sampler = _StubSampler()
    sampler.sample = _fail_if_called  # type: ignore[method-assign]

    result = _extractor(frame_sampler=sampler, frame_analyzer=None).extract(URL)

    assert result is not None
    assert result.frames_read is False


def _fail_if_called(*args, **kwargs):
    raise AssertionError("frames should not be sampled with no analyzer configured")
