"""Which frames get read, and why. Pure logic — no video, no codec, no
network — so the decision can be argued with directly."""

from __future__ import annotations

from reel_vault.media import choose_frame_indexes


def test_one_frame_per_scene_taken_from_its_middle() -> None:
    """Not a scene's first frame: a cut opens mid-transition, and a text card
    is legible only once it has settled."""
    chosen = choose_frame_indexes([0, 100, 200], total_frames=300, max_frames=3)

    assert chosen == [49, 149, 249]


def test_leftover_budget_is_spent_on_evenly_spread_frames() -> None:
    """Measured on a four-card test clip, the detector reported two cuts and
    the two cards it merged went unsampled: a card can change while the
    frame's overall composition barely does. The cap is the cost, so leaving
    it unspent buys nothing and loses coverage."""
    chosen = choose_frame_indexes([0, 40], total_frames=80, max_frames=6)

    # The scene midpoints are still there ...
    assert 19 in chosen and 59 in chosen
    # ... and the rest of the budget went on covering the gaps.
    assert len(chosen) == 6
    assert chosen == sorted(chosen)


def test_topping_up_never_repeats_a_frame_already_chosen() -> None:
    chosen = choose_frame_indexes([0, 50], total_frames=100, max_frames=8)

    assert len(chosen) == len(set(chosen))


def test_a_video_with_no_detected_cut_still_yields_frames() -> None:
    """A single continuous shot describes a talking head with text burned
    into it just as well as it describes an empty video."""
    chosen = choose_frame_indexes([], total_frames=100, max_frames=4)

    assert len(chosen) == 4
    assert chosen == sorted(chosen)
    # Never the very first or very last frame — lead-ins and end cards.
    assert 0 not in chosen
    assert 99 not in chosen


def test_more_scenes_than_the_cap_are_spread_across_the_whole_video() -> None:
    """Truncating to the first N would read a reel's setup and miss its
    payoff, which is usually the last thing on screen."""
    scene_starts = [at * 10 for at in range(20)]

    chosen = choose_frame_indexes(scene_starts, total_frames=200, max_frames=4)

    assert len(chosen) == 4
    assert chosen[0] < 20
    assert chosen[-1] > 180


def test_the_cap_is_never_exceeded() -> None:
    scene_starts = [at * 2 for at in range(100)]

    chosen = choose_frame_indexes(scene_starts, total_frames=200, max_frames=8)

    assert len(chosen) <= 8


def test_no_duplicate_frames_are_ever_returned() -> None:
    """A repeated frame is a wasted vision call, not a second reading."""
    chosen = choose_frame_indexes([0, 1, 2, 3, 4], total_frames=5, max_frames=4)

    assert len(chosen) == len(set(chosen))


def test_an_empty_video_yields_nothing() -> None:
    assert choose_frame_indexes([0, 10], total_frames=0) == []
    assert choose_frame_indexes([], total_frames=0) == []


def test_scene_starts_beyond_the_video_are_ignored() -> None:
    """Detectors can report a boundary at the very end; a scene with no
    frames in it is not a scene."""
    chosen = choose_frame_indexes([0, 50, 500], total_frames=100)

    assert all(0 <= index < 100 for index in chosen)


def test_asking_for_more_frames_than_the_video_has_is_bounded_by_the_video() -> None:
    chosen = choose_frame_indexes([], total_frames=3, max_frames=10)

    assert len(chosen) <= 3
    assert all(0 <= index < 3 for index in chosen)
