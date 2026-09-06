"""Guards on the three things `FRAME_PROMPT` has to keep saying.

The prompt that shipped before this one framed the whole task as reading text
*cards*. A whiteboard is not a card, so a reel whose entire content was two
hand-drawn diagrams came back described rather than read -- "each facing a
whiteboard on which they are drawing diagrams" -- with every label on both
boards missing, though all of them were legible in every sampled frame.
Diagnosed in `.scratch/reel-vault-media-pipeline/STATUS.md`: not a sampling
bug, not a legibility one, just the prompt's scope.

Widening it is what the A/B recorded there also showed to be dangerous, in
two specific ways, and this prompt carries a rule against each. Both were
re-measured on 2026-08-31 against `gemini-2.5-flash` at temperature 0.0, on
the eight frames `scripts/dump_reel_frames.py` pulls from that same reel
(https://instagram.com/p/DcoQRJKguIZ):

    shipped-before prompt   0 of 12 whiteboard labels; both incidental
                            overlays transcribed in full, which was most of
                            the output; "3 hour" read as "3.5 hour"
    this prompt, 3 runs     all 12 labels, grouped per board, every run;
                            each overlay reduced to a one-line naming;
                            no invented figures, "(illegible)" instead

No live call is made here. These are cheap assertions that the wording those
measurements depended on is still in the prompt.
"""

from __future__ import annotations

from reel_vault.adapters.vision import FRAME_PROMPT


def test_the_prompt_names_handwriting_and_diagram_labels_as_text() -> None:
    """The whole fix for the whiteboard reel. "On-screen text" alone did not
    reach a diagram drawn by hand; naming it did."""
    assert "handwriting and diagram labels" in FRAME_PROMPT
    assert "text to read, not scenery to describe" in FRAME_PROMPT


def test_the_prompt_still_names_text_cards_and_burned_in_captions() -> None:
    """Widening must not have come at the cost of the case that already
    worked. Text cards are how most reels in this vault carry their content,
    and they were never the problem."""
    assert "text cards and title slides" in FRAME_PROMPT
    assert "captions and labels burned into the frame" in FRAME_PROMPT


def test_the_prompt_forbids_guessing_at_an_unclear_value() -> None:
    """Told to read everything, the model rendered a pay table it could not
    quite resolve as round six-figure sums. The real reading is quoted in the
    prompt as the worked example; the fabrication deliberately is not.

    That is not fastidiousness. An earlier draft of this rule quoted the
    invented figures too, and the very next run copied them straight out of
    the prompt into its answer -- the counter-example handed the model the
    wrong answer to reach for."""
    assert "Never guess at an unclear value" in FRAME_PROMPT
    assert "(illegible)" in FRAME_PROMPT
    assert "Base: 145k, Signing bonus: 20k, Relocation: 3k, Stock: 90k" in FRAME_PROMPT

    for fabricated in ("$200,000", "$20,000", "$100,000"):
        assert fabricated not in FRAME_PROMPT, (
            f"{fabricated} was invented, not read. Quoting it here is what "
            "made a previous draft reproduce it verbatim."
        )


def test_the_prompt_scopes_reading_to_what_the_video_is_presenting() -> None:
    """The other half of the widening risk. Asked to read everything, the
    model transcribed a pasted-in screenshot of a stranger's job-offer post --
    paragraphs of it, in a reel about retrieval architectures, and the largest
    single block in that reel's stored reading. Noise at that volume does not
    just add nothing to retrieval, it outweighs what the reel is actually
    about."""
    assert "only along for the ride" in FRAME_PROMPT
    assert "ONE line naming what it is" in FRAME_PROMPT
    assert "a testimonial, a comment section, a chat, or" in FRAME_PROMPT


def test_the_prompt_does_not_ask_for_everything_visible() -> None:
    """The failed wider draft, pinned by its shape rather than its wording:
    an instruction to transcribe every piece of text on screen is what
    produced both failures above at once."""
    assert "EVERY piece of on-screen text" not in FRAME_PROMPT
