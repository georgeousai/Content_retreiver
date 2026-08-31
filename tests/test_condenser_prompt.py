"""Regression tests for the condenser wrongly emptying real content.

`ChatContentCondenser` returns "" when a reel's transcript carries nothing
worth keeping. Measured live on 2026-08-31 against `openai/gpt-oss-20b` at
temperature 0.0, it also emptied transcripts that were full of substance:

    chicken recipe (713 chars)   emptied  9/10   should keep
    Hindi interview-prep (710)   emptied  4/10   should keep
    RAG pipeline (2304 chars)    emptied  8/10   should keep
    fragrance intro (157 chars)  emptied 10/10   correct
    "." / "Thank you."           emptied 10/10   correct

An emptied transcript is not a visible failure — the reel is still marked
`done`, and the content is simply never searchable — so the guard has to be
a test rather than something noticed in use.

The attempted fix follows the pattern `.scratch/known-issues.md` records for
the summarizer's caption-crediting hallucination: an abstract rule did not
hold there, and a concrete counter-example naming the exact failure shape
did. The counter-example here is the chicken recipe below, verbatim.

**Whether it works is not yet established, and the prompt as it ships here
has never been run against a model.** Establishing the baseline above
exhausted the provider's 200,000-tokens-per-day cap. Two samples squeezed
through afterwards — one emptied the recipe, one condensed it correctly —
but both were against a longer draft of the prompt that has since been
trimmed, so they do not measure what is committed. The live tests at the
bottom of this file are how to find out; run them before calling this fixed.

The default run is hermetic: it pins the real transcripts and asserts the
prompt still carries the counter-example, which is what regresses when
someone tidies the prompt. Set RUN_LIVE_MODEL_TESTS=1 to also re-run the
measurement above against the configured provider.
"""

from __future__ import annotations

import os

import pytest

from reel_vault.adapters.llm import CONDENSE_SYSTEM_PROMPT

# `transcript_raw` for https://instagram.com/p/CuXvHE1Npbp (@buzzfeedtasty),
# copied verbatim out of the live vault. 713 characters.
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

# `transcript_raw` for https://instagram.com/p/DcljVtcOgEP (@realutkrsh).
# The control: this one genuinely is only a hook, and emptying it is right.
FRAGRANCE_HOOK_TRANSCRIPT = (
    "The best compliment any stranger can give you is that you smell good. So "
    "here are five fragrances that have been getting me a lot of compliments "
    "this summer."
)

# Whisper's own artifacts on silent or musical audio.
WHISPER_ARTIFACTS = [".", "Thank you."]


def test_the_hindi_transcript_has_not_been_trimmed() -> None:
    """Pinned for the same reason and with the same fragility: nothing else
    in the repo holds this text, so a silent edit would lose the second
    failure case outright."""
    assert len(HINDI_INTERVIEW_TRANSCRIPT) == 710


def test_the_pinned_transcript_has_not_been_trimmed() -> None:
    """The constant above is the measurement's subject and the prompt's
    counter-example at once. `test_the_prompt_names_the_recipe...` only
    proves the two agree with each other, so an edit applied to both would
    pass while silently no longer being the text that failed. The measured
    length is the one fact tying it back to `transcript_raw` in the vault."""
    assert len(CHICKEN_RECIPE_TRANSCRIPT) == 713


def test_the_prompt_names_the_recipe_that_was_wrongly_emptied() -> None:
    """The whole attempted fix is that this example is in the prompt, spelled
    out. A rewrite that trims it back to an abstract rule is the regression
    this file exists to catch."""
    assert CHICKEN_RECIPE_TRANSCRIPT in CONDENSE_SYSTEM_PROMPT


def test_the_prompt_still_allows_an_empty_reply() -> None:
    """The counter-example must not have talked the model out of emptying
    anything at all: Whisper's "." and "Thank you." still have to come back
    empty rather than be padded into a fake summary.

    This is the one prose assertion kept. The rest of the added wording is
    deliberately not pinned — coupling tests to editorial phrasing turns
    every rewording into a red build, and the recipe above is the part that
    actually has to survive."""
    assert "reply with an empty string" in CONDENSE_SYSTEM_PROMPT


# --- Live measurement, opt-in -------------------------------------------------

LIVE_RUNS = 5
# Stochastic even at temperature 0.0, exactly as the summarizer hallucination
# in `known-issues.md` was. One clean run proves nothing, so the bar is a
# rate over repeats, and it is set below 5/5 so a single slip is not a red
# build on a genuinely fixed prompt.
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

    config = load_config()
    return ChatContentCondenser(client=chat_client(config.llm), model=config.llm.model)


@live_only
def test_live_the_recipe_transcript_is_condensed_not_emptied(condenser) -> None:
    kept = [
        summary
        for _ in range(LIVE_RUNS)
        if (summary := condenser.condense(CHICKEN_RECIPE_TRANSCRIPT))
    ]
    assert len(kept) >= REQUIRED_NON_EMPTY, (
        f"emptied {LIVE_RUNS - len(kept)}/{LIVE_RUNS} times; "
        "the condense prompt has regressed"
    )
    # Emptying is the failure being guarded, but a summary that kept none of
    # the specifics would be the same content loss wearing a different shape.
    assert any("honey" in summary.lower() for summary in kept)


@live_only
def test_live_the_hindi_transcript_is_condensed_not_emptied(condenser) -> None:
    """The second confirmed failure, and the one the counter-example does not
    name — the prompt's worked example is an English recipe. If the recipe
    passes and this does not, one counter-example was not enough and this
    transcript is the next one to add."""
    kept = [
        summary
        for _ in range(LIVE_RUNS)
        if (summary := condenser.condense(HINDI_INTERVIEW_TRANSCRIPT))
    ]
    assert len(kept) >= REQUIRED_NON_EMPTY, (
        f"emptied {LIVE_RUNS - len(kept)}/{LIVE_RUNS} times "
        f"(baseline before the prompt change: 4/10)"
    )


@live_only
def test_live_a_bare_hook_is_still_emptied(condenser) -> None:
    """The other direction: the counter-example must not have turned the
    condenser into something that never empties anything."""
    emptied = sum(
        1 for _ in range(LIVE_RUNS) if not condenser.condense(FRAGRANCE_HOOK_TRANSCRIPT)
    )
    assert emptied >= REQUIRED_NON_EMPTY


@live_only
@pytest.mark.parametrize("artifact", WHISPER_ARTIFACTS)
def test_live_whisper_artifacts_are_still_emptied(condenser, artifact: str) -> None:
    assert condenser.condense(artifact) == ""


@live_only
def test_live_the_worked_example_does_not_leak_into_other_summaries(condenser) -> None:
    """A counter-example this long sits in the system prompt for every call,
    and the condenser's first rule is to add nothing. Cheap insurance that the
    recipe does not bleed into a reel that has nothing to do with cooking."""
    summary = condenser.condense(
        "Wake up at five. Cold shower every morning. Journal before you touch "
        "your phone. Walk for twenty minutes before you open a laptop. No "
        "caffeine until you have had a full glass of water."
    ).lower()

    for leaked in ("honey", "chili", "chicken", "paprika", "tenderloin"):
        assert leaked not in summary, f"the prompt's recipe example leaked: {leaked}"
