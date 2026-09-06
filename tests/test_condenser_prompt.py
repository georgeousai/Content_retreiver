"""Regression tests for the condenser returning nothing for real content.

For several sessions this looked like a judgement problem. `ChatContentCondenser`
came back empty for transcripts full of substance, and the rate looked like a
model being bad at deciding what mattered:

    openai/gpt-oss-20b   emptied the 713-char chicken recipe    9/10
    openai/gpt-oss-20b   emptied the 710-char Hindi transcript  4/10
    openai/gpt-oss-20b   emptied a 2304-char RAG walkthrough    8/10

It was not a judgement problem. **`gpt-oss-20b` is a reasoning model, and it
was spending its entire output budget thinking.** The reply came back with
`finish_reason="length"`, 2046 reasoning tokens out of 2048, and zero tokens
left to answer with — and the adapter turned that into `""`, which is
byte-for-byte what a model deliberately saying nothing looks like.

Everything the rate seemed to show follows from that, including the parts
that made no sense at the time: why longer transcripts failed more often
(more to reason about), why it varied at temperature 0.0 (reasoning length
drifts run to run), why a retry never helped (same input, same overflow), and
why a second provider behaved completely differently (it is not a reasoning
model in the same way).

The fix is in `adapters/llm.py`: `reasoning_effort="low"` on the condense
call, which answers the same question in 101 reasoning tokens instead of
2046, and a `TruncatedResponse` raised rather than an empty string returned
when a reply is cut off before it starts. After it, on the same model and
the same transcripts: recipe 5/5 kept, Hindi 5/5 kept.

**What was tried before, and undone.** The empty replies were read as
judgement, so the prompt was rewritten to argue against them — the emptied
recipe pasted in verbatim as a counter-example. It appeared to help and made
things worse: the model, taught to look harder for something to keep, went
from correctly emptying a content-free hook 10/10 to 0/5. Then the judgement
was moved out of the prompt into code entirely. Measured after the real fix,
the plain prompt and the "always condense" prompt score identically — recipe
5/5, Hindi 3/3, hook emptied 3/3 — so the argument was removed and the model
has its judgement back. What survives of that detour is
`reel_vault.substance`, which skips the model call for text with nothing in
it, and is now a cost saving rather than a correction.

The lesson, since this cost days: an empty response is not an answer until
you have checked `finish_reason`.

The default run is hermetic. Set RUN_LIVE_MODEL_TESTS=1 to re-run the
measurement against whatever `CONDENSER_*` points at.
"""

from __future__ import annotations

import os

import pytest

from reel_vault.adapters.llm import CONDENSE_SYSTEM_PROMPT

# `transcript_raw` for https://instagram.com/p/CuXvHE1Npbp (@buzzfeedtasty),
# copied verbatim out of the live vault. 713 characters. The text the
# condenser threw away 9 times in 10.
CHICKEN_RECIPE_TRANSCRIPT = (
    "Spicy Honey Garlic Chicken. Sweet, sticky, thick and pretty. What else "
    "would you want? Now we're gonna make our brine seasonings. Now put this "
    "in the fridge for at least an hour. For the wet batter, make this an "
    "hour ahead of time as well. For our seasoned flour, spices. Our "
    "tenderloin has been drained and dried. Plain flour, wet batter, and into "
    "the seasoned flour. Press hard and immediately fry your chicken. Fry for "
    "the second time for one to two minutes. Let's Make our honey garlic "
    "sauce, butter, add your garlic, cook it for three to four minutes, then "
    "a teaspoon of paprika, get that color. Add your honey and soy sauce. A "
    "tablespoon of hot chili flakes, half a teaspoon of salt. Paint your "
    "masterpiece."
)

# `transcript_raw` for https://instagram.com/p/DclrBDUt0Bi (@wdf_ai), the
# second confirmed failure: a Hindi-language video about an interview-prep
# site, emptied 4/10. Pinned here because this is the only copy outside the
# live vault — it was never written down anywhere that git tracked.
# 710 characters.
HINDI_INTERVIEW_TRANSCRIPT = (
    "यह देखो अगर तुम इंटर्वियो के प्रैक्टिस कर रहे हो तो इस वेबसाइट को "
    "गलती से भी मिस मत करना इसमें तुम्हें Meta, Netflix और Anthropik "
    "जैसी Companies के Real Interview Experience, Company Specific "
    "Quotient और Guide सब कुछ एक जगा मिल जाता है और अभी रुको इसमें "
    "तुम्हें Coding Quotient के साथ में System Design के Quotient भी "
    "मिल जाते हैं जिसको तुम Practice कर सकते हो और इसके साथ में इसमें "
    "एक forum भी है जिसमें तुम सारी चीज़ों को discuss भी कर सकते हो "
    "वैसे तो ये website pay daily कि तुम इसको free में यूज़ कर सकते हो "
    "कर्मा point को यूज़ करके जो तुमें community के अंदर contribute "
    "करने पर मिल जाते हैं और अगर तुम्हें इसका डिरेक्ट लिंक चाहिए तो बस "
    "कॉमेंट के अंदर इंटर्वियू लिखे दो, मैं सिधे तुमारे डियम में बेज "
    "दूँगा. "
).strip()


def test_the_hindi_transcript_has_not_been_trimmed() -> None:
    """Pinned for the same reason and with the same fragility: nothing else
    in the repo holds this text, so a silent edit would lose the second
    failure case outright."""
    assert len(HINDI_INTERVIEW_TRANSCRIPT) == 710


def test_the_pinned_transcript_has_not_been_trimmed() -> None:
    """The measured subject of the 9/10 failure. The length is the one fact
    tying this constant back to `transcript_raw` in the live vault."""
    assert len(CHICKEN_RECIPE_TRANSCRIPT) == 713


def test_the_prompt_still_lets_the_model_empty_a_hook() -> None:
    """This judgement is the model's, and it makes it well.

    That was not obvious. While its answers were being truncated the model
    looked incapable of it, and the instruction was briefly replaced with
    "always condense, never reply empty" so that code could own the call
    instead. Measured after the truncation was fixed, both prompts scored
    identically -- recipe 5/5, Hindi 3/3, hook emptied 3/3 -- so the plainer
    one that says what is actually wanted was kept.
    """
    assert "reply with an empty string" in CONDENSE_SYSTEM_PROMPT


def test_the_prompt_does_not_carry_a_verbatim_counter_example() -> None:
    """The chicken recipe was pasted into this prompt to argue the model out
    of emptying it. It was never the fix -- the emptying was truncation -- and
    it cost ~1200 characters on a call made twice per reel, while teaching
    the model to keep content-free hooks it had been emptying correctly."""
    assert CHICKEN_RECIPE_TRANSCRIPT not in CONDENSE_SYSTEM_PROMPT
    assert len(CONDENSE_SYSTEM_PROMPT) < 2000


def test_the_prompt_still_forbids_inventing_detail() -> None:
    """The rule that was never in question, and must survive the trimming:
    the summarizer's caption-crediting hallucination in `known-issues.md` is
    what it is there for."""
    assert "Add NOTHING" in CONDENSE_SYSTEM_PROMPT


# --- Live measurement, opt-in -------------------------------------------------

LIVE_RUNS = 5
# Stochastic even at temperature 0.0, exactly as the summarizer hallucination
# in `known-issues.md` was. One clean run proves nothing, so the bar is a rate
# over repeats, set below 5/5 so a single slip is not a red build.
REQUIRED_NON_EMPTY = 4

live_only = pytest.mark.skipif(
    not os.environ.get("RUN_LIVE_MODEL_TESTS"),
    reason="set RUN_LIVE_MODEL_TESTS=1 to call the configured provider",
)


@pytest.fixture(scope="module")
def condenser():
    from dotenv import load_dotenv

    load_dotenv()
    from reel_vault.adapters.llm import ChatContentCondenser, chat_client
    from reel_vault.config import load_config

    # `config.condenser`, not `config.llm`: which model this ran against is
    # the whole point of the measurement, and CONDENSER_* is how it gets
    # pointed at a second provider for comparison.
    config = load_config()
    print(
        f"\ncondenser under test: {config.condenser.model} "
        f"at {config.condenser.base_url}"
    )
    return ChatContentCondenser(
        client=chat_client(config.condenser), model=config.condenser.model
    )


@live_only
def test_live_the_recipe_transcript_is_condensed_not_emptied(condenser) -> None:
    """The original bug, measured end to end. This transcript reaches the
    model at all only because `has_substance` says it should; what is under
    test here is that the model then does its half."""
    kept = [
        summary
        for _ in range(LIVE_RUNS)
        if (summary := condenser.condense(CHICKEN_RECIPE_TRANSCRIPT))
    ]
    assert len(kept) >= REQUIRED_NON_EMPTY, (
        f"emptied {LIVE_RUNS - len(kept)}/{LIVE_RUNS} times "
        f"(baseline with the old prompt: 9/10 on gpt-oss-20b)"
    )
    # Emptying is the failure being guarded, but a summary that kept none of
    # the specifics would be the same content loss wearing a different shape.
    assert any("honey" in summary.lower() for summary in kept)


@live_only
def test_live_the_hindi_transcript_is_condensed_not_emptied(condenser) -> None:
    """The second confirmed failure, and the one no English counter-example
    ever addressed directly."""
    kept = [
        summary
        for _ in range(LIVE_RUNS)
        if (summary := condenser.condense(HINDI_INTERVIEW_TRANSCRIPT))
    ]
    assert len(kept) >= REQUIRED_NON_EMPTY, (
        f"emptied {LIVE_RUNS - len(kept)}/{LIVE_RUNS} times "
        f"(baseline with the old prompt: 4/10 on gpt-oss-20b)"
    )


@live_only
def test_live_a_terse_transcript_is_not_mistaken_for_an_empty_one(
    condenser,
) -> None:
    """The shape that used to trip it: clipped, list-like, instruction-shaped
    text with half the quantities dropped. Nothing in code protects this if
    the model decides it is too thin — `has_substance` has already said it is
    not, and the prompt is what has to hold from here."""
    summary = condenser.condense(
        "wake up at five. cold shower. journal before your phone. "
        "walk twenty minutes before the laptop. no caffeine before water."
    )
    assert summary.strip(), "a terse but real transcript came back empty"
