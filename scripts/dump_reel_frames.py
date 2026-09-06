"""Save to disk exactly the frames `SceneDetectFrameSampler` hands the vision
model for one reel, alongside the sampling decision that picked them.

Not part of the app and not a test — a diagnostic. When a reel's
`frame_analysis_raw` is missing something that was plainly on screen, there
are two very different explanations, and they need opposite fixes: the
sampler never picked a frame showing it (coverage), or it did and the model
did not read it (legibility, or the vision prompt's scope). Guessing between
them means changing sampling logic that may be innocent, so this script
exists to settle it by looking.

Usage:

    uv run python scripts/dump_reel_frames.py <reel-url> <output-dir>

Writes the sampled frames, a `sampling.json` recording the scene starts and
chosen indexes, and an `all/` contact sheet of every 15th frame so what the
sampler picked can be compared against what the video actually contained.

The frames themselves come from `SceneDetectFrameSampler.sample()` rather
than from a reimplementation of it, so what lands on disk is what production
sends and cannot drift from it. The numbers in `sampling.json` are
re-derived — the sampler returns images, not the reasoning behind them — so
they are a second reading of the same inputs, not the sampler's own record.

The video is downloaded into the output directory and left there; unlike the
pipeline, this script is a deliberate manual inspection, so it does not clean
up behind itself. Delete the directory when you are done — the project does
not store media.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
from scenedetect import ContentDetector, detect

from reel_vault.adapters.media import SceneDetectFrameSampler, YtDlpVideoDownloader
from reel_vault.media import MAX_FRAMES, choose_frame_indexes

CONTACT_SHEET_STRIDE = 15


def main(url: str, outdir: Path) -> int:
    outdir.mkdir(parents=True, exist_ok=True)

    video = YtDlpVideoDownloader().download(url, outdir)
    if video is None:
        print(f"could not download {url}")
        return 1
    print(f"downloaded: {video}")

    frames = SceneDetectFrameSampler().sample(video, MAX_FRAMES)
    if not frames:
        print("the sampler returned no frames")
        return 1

    info = _describe_sampling(video, url)

    # Labelled against the indexes that actually decoded, not against every
    # index the chooser picked. The sampler silently drops an index it cannot
    # read, so its output is shorter than its input whenever a chosen frame
    # is unreadable — and zipping images against the full list slid every
    # label after the first gap by one, mislabelling precisely the
    # frame-to-timestamp correspondence this script exists to establish.
    labels: list[int | None] = list(info["decoded_indexes"])
    if len(labels) != len(frames):
        print(
            f"warning: {len(frames)} frames returned for {len(labels)} decodable "
            f"indexes — writing them unnumbered rather than guessing which is which"
        )
        labels = [None] * len(frames)

    for nth, (frame, index) in enumerate(zip(frames, labels)):
        if index is None:
            name = f"frame_{nth:02d}.jpg"
        else:
            at = f"t{index / info['fps']:.1f}s" if info["fps"] else "t?"
            name = f"frame_{nth:02d}_idx{index}_{at}.jpg"
        (outdir / name).write_bytes(frame)
    info["frames_written"] = len(frames)

    _write_contact_sheet(video, outdir / "all", info)

    (outdir / "sampling.json").write_text(json.dumps(info, indent=2))
    print(json.dumps(info, indent=2))
    return 0


def _describe_sampling(video: Path, url: str) -> dict:
    """Re-derive why the sampler chose what it chose.

    Detection is wrapped exactly as `SceneDetectFrameSampler.sample` wraps it
    — a failure there means an empty scene list and an evenly-spread fallback,
    not an exception — so this reading agrees with the sampler's on the one
    case where a naive copy would silently disagree with it.
    """
    capture = cv2.VideoCapture(str(video))
    try:
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = capture.get(cv2.CAP_PROP_FPS) or 0.0
        resolution = [
            int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        ]
    finally:
        capture.release()

    try:
        starts = [scene[0].frame_num for scene in detect(str(video), ContentDetector())]
    except Exception as exc:
        print(f"scene detection failed ({exc}); the sampler falls back to even spacing")
        starts = []

    chosen = choose_frame_indexes(starts, total, MAX_FRAMES)
    decoded = _decodable(video, chosen)
    return {
        "url": url,
        "total_frames": total,
        "fps": fps,
        "duration_s": round(total / fps, 2) if fps else None,
        "resolution": resolution,
        "scene_starts": starts,
        "chosen_indexes": chosen,
        "chosen_times_s": [round(i / fps, 2) for i in chosen] if fps else None,
        # Both are recorded, because the difference between them is itself a
        # finding: an index the chooser picked and the decoder could not read
        # is a frame production never saw either.
        "decoded_indexes": decoded,
        "undecodable_indexes": [i for i in chosen if i not in set(decoded)],
    }


def _decodable(video: Path, indexes: list[int]) -> list[int]:
    """Which of the chosen indexes actually yield a frame, in order.

    The same seek-and-read `SceneDetectFrameSampler._encode_frame` does, for
    the same reason: what the sampler hands back is only the subset it could
    decode, and this script's whole job is to say which frame is which.
    """
    capture = cv2.VideoCapture(str(video))
    try:
        readable = []
        for index in indexes:
            capture.set(cv2.CAP_PROP_POS_FRAMES, index)
            read, _ = capture.read()
            if read:
                readable.append(index)
        return readable
    finally:
        capture.release()


def _write_contact_sheet(video: Path, into: Path, info: dict) -> None:
    """Every Nth frame, so what the sampler picked can be read against what
    the video actually held at the moments it skipped."""
    into.mkdir(exist_ok=True)
    fps = info["fps"]
    capture = cv2.VideoCapture(str(video))
    try:
        for index in range(0, info["total_frames"], CONTACT_SHEET_STRIDE):
            capture.set(cv2.CAP_PROP_POS_FRAMES, index)
            read, frame = capture.read()
            if not read:
                continue
            encoded, buffer = cv2.imencode(".jpg", frame)
            if not encoded:
                continue
            at = f"{index / fps:06.2f}" if fps else str(index)
            (into / f"t{at}s_idx{index}.jpg").write_bytes(bytes(buffer))
    finally:
        capture.release()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], Path(sys.argv[2])))
