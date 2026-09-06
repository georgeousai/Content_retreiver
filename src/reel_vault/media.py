"""Which frames of a reel are worth looking at.

Kept apart from the adapter that decodes video so the decision itself can be
reasoned about and tested without opencv, a codec, or a real file — the same
split that keeps `reel_vault.search` separate from the store that runs its
queries.
"""

from __future__ import annotations

# Enough frames to cover a reel's on-screen text cards, few enough that one
# unusually choppy video cannot spend a free-tier quota by itself. Every
# frame is an image in a vision prompt, so this is the cost knob.
MAX_FRAMES = 8


def choose_frame_indexes(
    scene_starts: list[int], total_frames: int, max_frames: int = MAX_FRAMES
) -> list[int]:
    """The frames to pull out of a video, given where its scenes begin.

    One frame from the middle of each scene, rather than one every N seconds.
    The reels this vault holds carry their substance as a run of on-screen
    text cards, and a fixed interval lands wherever it lands: it can fall
    between two cards and catch neither, or sample the same held shot twice
    while a card that flashed by for half a second is never seen at all. A
    scene change is the video telling us the picture is now different, which
    is exactly the moment worth reading.

    The middle of a scene, not its first frame: a cut's first frames are
    often mid-transition — a fade, a blur, a half-drawn overlay — and a text
    card is legible once it has settled.

    Detection finding few scenes does not mean there is little to read.
    Measured on a four-card test clip, the detector reported two cuts and the
    two cards it merged were never sampled: an on-screen card can change
    while the frame's overall composition barely does, which is exactly what
    a content detector scores on. So when the scenes come to fewer frames
    than the budget allows, the remainder is filled with evenly-spread ones
    rather than left unspent. Scene changes say where the picture is
    certainly different; the fill covers where it might be. Spending the
    whole budget costs nothing extra — the cap is the cost — and only ever
    adds coverage.

    That also covers a video with no detected cut at all, which describes a
    talking-head reel with a caption burned into it just as well as it
    describes an empty one.

    When there are more scenes than the cap allows, the kept frames are
    spread across the whole video rather than being the first `max_frames` of
    them — a reel's payoff is usually at the end, and truncating would read
    the setup and miss the answer.
    """
    if total_frames <= 0 or max_frames <= 0:
        return []

    chosen = _thin_evenly(_scene_midpoints(scene_starts, total_frames), max_frames)
    if len(chosen) < max_frames:
        chosen = _topped_up(chosen, total_frames, max_frames)
    return chosen


def _scene_midpoints(scene_starts: list[int], total_frames: int) -> list[int]:
    starts = sorted({start for start in scene_starts if 0 <= start < total_frames})
    if len(starts) < 2:
        # One scene is no more informative than none: the detector found no
        # cut, so there is nothing to centre on and the even fallback applies.
        return []

    boundaries = [*starts, total_frames]
    return [
        (boundaries[at] + boundaries[at + 1] - 1) // 2
        for at in range(len(boundaries) - 1)
    ]


def _topped_up(chosen: list[int], total_frames: int, max_frames: int) -> list[int]:
    """Spend the rest of the frame budget on evenly-spread frames.

    The fill is thinned across the whole candidate run rather than taken from
    the front of it. Taking the first few that fit put five of eight frames
    in the opening seconds of a test clip and never reached its last card —
    the exact clustering this function exists to avoid, arrived at from the
    other direction.

    Candidates that land on a frame already chosen are dropped first, so a
    scene midpoint is never paid for twice.
    """
    needed = max_frames - len(chosen)
    kept = set(chosen)
    candidates = [
        candidate
        for candidate in _evenly_spaced(total_frames, max_frames * 2)
        if candidate not in kept
    ]
    kept.update(_thin_evenly(candidates, needed))
    return sorted(kept)[:max_frames]


def _evenly_spaced(total_frames: int, count: int) -> list[int]:
    """`count` frames spread across the video, each in the middle of its own
    slice — so the first is not frame zero (often a black lead-in) and the
    last is not the final frame (often an end card or a cut to black)."""
    wanted = min(count, total_frames)
    seen: dict[int, None] = {}
    for at in range(wanted):
        seen.setdefault(
            min(total_frames - 1, (2 * at + 1) * total_frames // (2 * wanted)), None
        )
    return list(seen)


def _thin_evenly(indexes: list[int], max_frames: int) -> list[int]:
    if max_frames <= 0:
        return []
    if len(indexes) <= max_frames:
        return indexes
    if max_frames == 1:
        # The middle one, not the first: a single frame of a reel is far more
        # likely to carry its content halfway through than at the opening cut.
        return [indexes[len(indexes) // 2]]
    kept = [
        indexes[at * (len(indexes) - 1) // (max_frames - 1)]
        for at in range(max_frames)
    ]
    # Thinning can land twice on the same scene when the list is barely over
    # the cap; a duplicate frame is a wasted call, not a second reading.
    return sorted(set(kept))
