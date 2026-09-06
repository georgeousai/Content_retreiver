"""The empty-or-keep decision, now that code makes it instead of a model.

Every case marked "live vault" is a real `transcript_raw` or
`frame_analysis_raw`, hand-labelled by reading it. Together they were the
whole of the media text the vault held on 2026-09-01 — sixteen pieces across
nine reels — which is the entire evidence base this rule was designed
against, so they are pinned here rather than described.

The measurement that moved this call out of the prompt, from
`.scratch/reel-vault-media-pipeline/STATUS.md`: asked to make it itself,
`openai/gpt-oss-20b` emptied the chicken recipe 9 times in 10; after the
prompt was rewritten to stop that, it kept a hook naming nothing 5 times in
5. `gemini-3.5-flash-lite` failed the same pair the same way.

**What this rule is tuned for is cost, not accuracy.** A wrongly emptied
transcript is content gone from search with nothing to show it went; a
wrongly kept hook is one bland sentence in an embedding. So the tests below
are split by which mistake they guard, and the "must never be emptied" half
is the half that matters.
"""

from __future__ import annotations

import pytest

from reel_vault.substance import has_substance

# --- live vault, verbatim -----------------------------------------------------

RECIPE_TRANSCRIPT = (
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

RECIPE_FRAMES = (
    "Wet Batter\n(Quang Tran Method)\n1/3 Cup Flour\n4 Oz Water\n1 Egg\n"
    "1st Fry: 5 min\n300 F (149 C)\n2nd Fry: 1 to 2 min\n350 F (177 C)"
)

FRAGRANCE_FRAMES = (
    "Maison Margiela\nNever Ending Summer\nLouis Vuitton\nImagination\n"
    "Michael Malul\nOcean Noir\nKilian\nMoonlight in Heaven\nDiptyque\n"
    "Tam Dao\n\nA man with a beard, wearing a denim shirt, sits in front of a "
    "bookshelf and presents a wooden tray holding five perfume bottles."
)

# The thinnest true keep in the vault: almost all scenery, but it names the
# place, which is exactly what someone would search for.
GOA_FRAMES = (
    "\U0001f4cd pisco by the beach, GOA\n\nThe video shows a dimly lit "
    "interior space, likely a restaurant or bar, with a person seated at a "
    "table on the left. Large glass doors look out onto a dark body of water."
)

# Hindi, and the reason `_names_something` cannot assume one script: every
# name in it is in Latin characters inside Devanagari prose.
HINDI_TRANSCRIPT = (
    "यह देखो अगर तुम इंटर्वियो के प्रैक्टिस कर रहे हो तो इस वेबसाइट को "
    "गलती से भी मिस मत करना इसमें तुम्हें Meta, Netflix और Anthropik "
    "जैसी Companies के Real Interview Experience सब कुछ एक जगा मिल जाता है"
)

# What Whisper returns for silence or music. Every one of these is a real
# `transcript_raw` from the vault, or the shape of one.
ARTIFACTS = [".", "Thank you.", "", "   ", "[Music]", "Thanks for watching!"]

# The content category the whole media pipeline exists for: spoken-only
# reels whose captions are comment-bait. Nearly half the vault. Names
# nothing, counts nothing, and must survive anyway.
HABITS_TRANSCRIPT = (
    "Wake up at five. Cold shower every morning. Journal before you touch "
    "your phone. Walk for twenty minutes before you open a laptop. No "
    "caffeine until you have had a full glass of water."
)
HABITS_FIXTURE = (
    "wake up at five\ncold shower every morning\njournal before your phone"
)


# --- the mistake that costs content -------------------------------------------

@pytest.mark.parametrize(
    "name, text",
    [
        ("recipe transcript (live vault)", RECIPE_TRANSCRIPT),
        ("recipe frames (live vault)", RECIPE_FRAMES),
        ("fragrance frames (live vault)", FRAGRANCE_FRAMES),
        ("goa frames (live vault)", GOA_FRAMES),
        ("hindi transcript (live vault)", HINDI_TRANSCRIPT),
        ("habits, as Whisper would return it", HABITS_TRANSCRIPT),
        ("habits, as tests/test_media.py fixes it", HABITS_FIXTURE),
        ("terse instruction", "add salt and pepper"),
        ("two words, one a name", "Use Notion"),
        ("no names, but numbers", "Rest 90 seconds, then do 3 sets of 12."),
    ],
)
def test_nothing_with_content_in_it_is_ever_emptied(name: str, text: str) -> None:
    """The half of this that matters. Each of these was emptied by a model on
    at least one measured run, or would be by an earlier draft of this rule.

    The two habits entries are the ones that killed the first draft. That
    draft emptied text naming nothing and counting nothing, which sounded
    principled until it turned out to describe every spoken-word reel in a
    vault where spoken-word reels are the point.
    """
    assert has_substance(text), f"{name} would be thrown away"


# --- the mistake that costs a little noise ------------------------------------

@pytest.mark.parametrize("artifact", ARTIFACTS)
def test_whisper_artifacts_are_emptied(artifact: str) -> None:
    """All this rule actually claims to catch: text with nothing in it.
    Manufacturing a summary from two words would be worse than nothing."""
    assert not has_substance(artifact)


def test_a_content_free_hook_is_kept_and_that_is_deliberate() -> None:
    """Pinned as accepted behaviour, not overlooked behaviour.

    This hook promises five fragrances and names none, so ideally it would be
    emptied. Code does not attempt it, because on this vault's own texts, by
    the module's own counting, the hook sits *between* two transcripts that
    must both be kept:

        fragrance hook, must empty      157 chars   13 real words
        habits transcript, must keep     67 chars    8 real words
        habits transcript, must keep    184 chars   19 real words

    No threshold on length or word count separates it from both. A rule that
    emptied the hook would empty a habits reel too, and one of those mistakes
    destroys content while the other adds a bland sentence to an embedding.

    The model does empty it, correctly and 3/3 when measured, which is why
    this call was left with the model. What is pinned here is only that code
    does not overrule it in either direction.
    """
    hook = (
        "The best compliment any stranger can give you is that you smell "
        "good. So here are five fragrances that have been getting me a lot "
        "of compliments this summer."
    )
    assert has_substance(hook)


# --- the pieces the rule is built from ----------------------------------------

SCRIPTS_WITHOUT_CAPITALS = {
    "devanagari": "यह देखो अगर तुम इंटरव्यू के प्रैक्टिस कर रहे हो तो इस वेबसाइट को मिस मत करना",
    "han": "今天我要教你怎么做红烧肉，首先准备五花肉和生姜",
    "arabic": "اليوم سأعلمك كيفية تحضير هذا الطبق اللذيذ خطوة بخطوة",
}


@pytest.mark.parametrize("script", sorted(SCRIPTS_WITHOUT_CAPITALS))
def test_a_transcript_in_any_script_survives(script: str) -> None:
    """A real bug this file did not catch at first, and the worst kind: every
    one of these was emptied, silently, by a Latin-only word pattern.

    Two of the three rules cannot fire here at all. `_names_something` looks
    for capitals, which none of these scripts has; `_counts_something` looks
    for digits, which prose need not contain. Everything therefore rests on
    `_says_enough`, and while it counted only `[A-Za-z]` it scored all of
    them at zero words and threw them away. This vault already holds one
    Hindi reel, and it passed only because it happens to name Meta and
    Netflix in Latin characters.
    """
    assert has_substance(SCRIPTS_WITHOUT_CAPITALS[script])


def test_cyrillic_prose_without_proper_nouns_survives() -> None:
    """Cyrillic has capitals, so `_names_something` could in principle fire —
    but only if the text happens to name something. Ordinary prose does not,
    which is why having capitals is not enough on its own."""
    assert has_substance("сегодня я покажу вам как приготовить это блюдо")


def test_a_short_artifact_in_another_script_is_still_emptied() -> None:
    """The letter-count fallback must not become "keep everything non-Latin".
    Whisper returns pleasantries in whatever language it heard."""
    assert not has_substance("谢谢")


def test_a_pronoun_is_not_a_name() -> None:
    """"I" is capitalised wherever it stands, so counting it as a name would
    make every first-person sentence look like it named something."""
    from reel_vault.substance import _names_something

    assert not _names_something("I think I'll do it. I've decided.")
    assert _names_something("I think Notion is better.")


def test_number_words_are_not_counted_as_numbers() -> None:
    """Deliberate: "here are five fragrances" naming none of them is the
    emptiest text in the vault, so number words cannot be evidence."""
    from reel_vault.substance import _counts_something

    assert not _counts_something("here are five things")
    assert _counts_something("1/3 cup flour")
