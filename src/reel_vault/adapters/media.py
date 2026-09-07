"""Reading a reel's video: download it, hear it, look at it, delete it.

The video file exists only for the length of one `extract` call. Nothing
durable is ever written — the project's "no stored media" decision is intact,
since what that decision protects against is disk and cost growing with the
size of the vault, not a file existing for ninety seconds.

The three steps are separate protocols so each can be swapped or faked, but
they are composed here rather than exposed to the vault: they share a file
that must not outlive them, and splitting them across vault-facing ports
would push that file's lifetime out into a caller with no reason to know
about it.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Protocol

from reel_vault.media import MAX_FRAMES
from reel_vault.models import MediaExtraction, MediaUnavailable

logger = logging.getLogger(__name__)


class VideoDownloader(Protocol):
    def download(self, url: str, into: Path) -> Path | None:
        """Fetch the reel's video into `into`, or None if it can't be had."""
        ...


class Transcriber(Protocol):
    def transcribe(self, media_path: Path) -> str:
        """The words spoken in the file, or "" if there are none to be had."""
        ...


class FrameSampler(Protocol):
    def sample(self, media_path: Path, max_frames: int) -> list[bytes]:
        """Encoded still images from the video, chosen at its scene changes."""
        ...


class FrameAnalyzer(Protocol):
    def analyze(self, frames: list[bytes]) -> str:
        """What the frames show and what text is on them."""
        ...


class VideoMediaExtractor:
    def __init__(
        self,
        *,
        downloader: VideoDownloader,
        transcriber: Transcriber,
        frame_sampler: FrameSampler,
        # None when no vision endpoint is configured. Deliberately not a
        # do-nothing analyzer returning "": that made "nobody looked" and
        # "nothing was on screen" the same value, and the reel was filed as
        # fully read either way. Absent means absent, and `extract` says so.
        frame_analyzer: FrameAnalyzer | None,
        max_frames: int = MAX_FRAMES,
    ) -> None:
        self._downloader = downloader
        self._transcriber = transcriber
        self._frame_sampler = frame_sampler
        self._frame_analyzer = frame_analyzer
        self._max_frames = max_frames

    def extract(self, url: str) -> MediaExtraction | None:
        """Everything the video carries, or None if the video was read and
        carried nothing. Raises `MediaUnavailable` if it could not be fetched
        at all.

        Those last two used to be the same answer, and the user was told
        neither. A post Instagram will not serve without a login came back
        indistinguishable from a video that downloaded fine and turned out to
        be silent with a blank screen -- both `None`, both filed FAILED, both
        reported as nothing at all.

        The audio and the picture fail independently. A reel whose speech
        transcribed cleanly but whose frames could not be read is still worth
        far more than the caption alone, so one failing does not discard the
        other's work.

        `frames_read` on the result separates a third case from those two:
        the frames were not read -- either never sent anywhere, because no
        vision model is configured, or sent and not answered, because the
        call failed. Neither is a finished read, and an empty
        `frame_analysis` cannot say which of the three happened on its own.

        The second cause was found the hard way: a reel with a full
        transcript and no frame text at all, marked DONE. The vision call had
        failed (a rate limit, most likely -- it was one of a burst of saves),
        `_read_frames` returned "" as it does for a video with nothing on
        screen, and `frames_read` was True because an analyzer *existed*. In
        the database that was indistinguishable from "we looked, there was
        nothing there", and nothing ever came back for it.
        """
        # TemporaryDirectory removes the tree on the way out of the block —
        # on success, on failure, and on an exception thrown through it. That
        # guarantee is the entire reason the download happens inside a
        # context manager rather than into a path we remember to clean up.
        with tempfile.TemporaryDirectory(prefix="reel-vault-") as workspace:
            video = self._download(url, Path(workspace))
            if video is None:
                raise MediaUnavailable(url)

            frame_analysis, frames_read = self._read_frames(video)
            extraction = MediaExtraction(
                transcript=self._transcribe(video),
                frame_analysis=frame_analysis,
                frames_read=frames_read,
            )

        if extraction.is_empty():
            logger.info("Nothing could be read from the video at %s", url)
            return None
        return extraction

    def _download(self, url: str, into: Path) -> Path | None:
        try:
            return self._downloader.download(url, into)
        except Exception as exc:
            logger.info("Could not download the video at %s: %s", url, exc)
            return None

    def _transcribe(self, video: Path) -> str:
        try:
            return self._transcriber.transcribe(video)
        except Exception as exc:
            logger.info("Transcription failed for %s: %s", video.name, exc)
            return ""

    def _read_frames(self, video: Path) -> tuple[str, bool]:
        """What the frames showed, and whether anyone actually looked.

        The second value is the one that used to be derived from "is an
        analyzer configured", which is a different question. An analyzer
        that exists and raises has not read anything, and saying it has is
        how a rate-limited reel ended up filed as finished.

        Reads as False whenever this does not know what is on the frames:
        no analyzer, sampling raised, analysis raised. Reads as True when it
        does know -- including knowing there was nothing, which is what a
        sampler returning no frames or an analyzer returning "" both mean.
        Uncertainty and emptiness are the two things the old code conflated.

        The failures log at WARNING, not INFO. A rate limit during a burst
        of saves is exactly the kind of thing that scrolls past unnoticed,
        and the person watching the terminal for it was told nothing.
        """
        if self._frame_analyzer is None:
            return "", False

        try:
            frames = self._frame_sampler.sample(video, self._max_frames)
        except Exception as exc:
            logger.warning(
                "Frame sampling failed for %s; frames left unread: %s",
                video.name,
                exc,
            )
            return "", False

        if not frames:
            return "", True

        try:
            return self._frame_analyzer.analyze(frames), True
        except Exception as exc:
            logger.warning(
                "Frame analysis failed for %s; frames left unread: %s",
                video.name,
                exc,
            )
            return "", False


class YtDlpVideoDownloader:
    """The real download, which the caption fetcher deliberately does not do.

    Kept separate from `YtDlpCaptionFetcher` rather than added as a flag on
    it: a save must stay as quick as it is today, and a fetcher that can
    download is one wrong argument away from making every save wait on a
    video.
    """

    # A reel is a phone-sized vertical video; the largest rendition buys
    # nothing for reading text off a frame and costs the whole download.
    FORMAT = "best[ext=mp4][height<=720]/best[ext=mp4]/best"

    def download(self, url: str, into: Path) -> Path | None:
        try:
            import yt_dlp
        except ImportError:  # pragma: no cover - dependency is always installed
            logger.warning("yt-dlp is not installed; cannot download video")
            return None

        options = {
            "quiet": True,
            "no_warnings": True,
            "format": self.FORMAT,
            "outtmpl": str(into / "%(id)s.%(ext)s"),
            "noplaylist": True,
        }
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)

        if not info:
            return None
        downloaded = ydl.prepare_filename(info)
        path = Path(downloaded)
        if path.exists():
            return path
        # yt-dlp reports the name it planned to use; a post-processor may
        # have changed the extension underneath us.
        candidates = sorted(into.glob(f"{path.stem}.*"))
        return candidates[0] if candidates else None


class SceneDetectFrameSampler:
    """Frames chosen where the picture actually changes.

    Scene detection rather than a fixed interval is a deliberate accuracy
    choice for this content: a reel's substance is often a run of on-screen
    text cards, and a timer samples wherever it happens to land — between two
    cards, or twice on the same held shot while a card that flashed by for
    half a second is never seen.
    """

    def sample(self, media_path: Path, max_frames: int) -> list[bytes]:
        try:
            import cv2
            from scenedetect import ContentDetector, detect
        except ImportError:  # pragma: no cover - dependency is always installed
            logger.warning("scenedetect/opencv missing; cannot sample frames")
            return []

        from reel_vault.media import choose_frame_indexes

        capture = cv2.VideoCapture(str(media_path))
        try:
            total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            if total <= 0:
                return []

            try:
                scenes = detect(str(media_path), ContentDetector())
                starts = [scene[0].frame_num for scene in scenes]
            except Exception as exc:
                # Detection failing is not fatal: an evenly-spread fallback
                # still reads a video, which is the point.
                logger.info("Scene detection failed for %s: %s", media_path.name, exc)
                starts = []

            return [
                encoded
                for index in choose_frame_indexes(starts, total, max_frames)
                for encoded in [_encode_frame(capture, index)]
                if encoded is not None
            ]
        finally:
            capture.release()


def _encode_frame(capture, index: int) -> bytes | None:
    import cv2

    capture.set(cv2.CAP_PROP_POS_FRAMES, index)
    read, frame = capture.read()
    if not read:
        return None
    encoded, buffer = cv2.imencode(".jpg", frame)
    return bytes(buffer) if encoded else None
