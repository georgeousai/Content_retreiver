"""Whether a piece of media text is worth handing to the condenser at all.

Kept apart from the adapter that condenses, so the decision can be tested
without a model, a key, or a network — the same split that keeps
`reel_vault.search` separate from the store that runs its queries, and
`reel_vault.media` separate from the codec.

**This is a cost saving, not a correctness fix.** It is worth being exact
about that, because this module was written while a different explanation was
believed. The condenser used to return nothing for transcripts full of
content — a 713-character recipe emptied 9 times in 10 — and that was read as
the model judging badly, which this module was built to take over. It was not
a judgement problem: the replies were being truncated before the model wrote
anything, and the adapter was returning the empty string that resulted. See
`adapters.llm.TruncatedResponse` and
`.scratch/reel-vault-media-pipeline/STATUS.md`.

With that fixed the model's judgement turned out to be good — it keeps the
recipe 5/5 and empties a content-free hook 3/3 — so the decision stayed with
it. What this module still buys is the calls it never has to make: Whisper's
`"."` on a silent clip and its `"Thank you."` over music are not judgement
calls, and paying a model twice a reel to make them is waste.

## What it does not try to do

It does not try to tell a content-free hook from a real list of instructions.
That is a semantic judgement, the model makes it well, and the obvious code
proxies cannot: measured on this vault's own texts, by this module's own
counting,

    fragrance hook, must empty      157 chars   13 real words
    habits transcript, must keep     67 chars    8 real words
    habits transcript, must keep    184 chars   19 real words

the hook sits *between* two texts that must both be kept, on both measures at
once. No threshold on length or word count separates it from both, and reels
whose content is spoken rather than captioned are nearly half this vault and
the whole reason the media pipeline exists.

## Which way it errs

The two mistakes do not cost the same, so this is tuned by cost rather than
by accuracy:

- **Wrongly emptied**: the words are gone from search. The reel still reads
  `done`, nothing looks broken, and nobody finds out until an answer is
  quietly worse for it.
- **Wrongly kept**: one model call that need not have happened, and a bland
  sentence in an embedding.

So it returns True on everything it is not certain about, and reaches False
only for text that names nothing, counts nothing, and says almost nothing in
any script.
"""

from __future__ import annotations

import re

# Words that say nothing on their own, so a text made only of them is a text
# with nothing in it. Kept short on purpose: this list exists to recognise
# Whisper's artifacts and outros, not to score how interesting a reel is.
FILLER = frozenset(
    """
    the and but for you your yours our ours their theirs this that these those
    with from into onto about over under just also very really quite still yet
    here there what which who whom whose when where why how all any some every
    each both few more most other such only own same than too can could will
    would shall should may might must have has had having been being does did
    doing thanks thank watching subscribe like comment share follow please
    """.split()
)

# Below this many distinct real words there is nothing to condense. Set at the
# very bottom of the range on purpose: "do six sets" is a whole instruction in
# two words, and every notch this climbs starts discarding terse content that
# meant something. Whisper's artifacts fall under it because their words are
# filler outright ("thanks for watching"), not because there are few of them.
MINIMUM_REAL_WORDS = 2

# How many letters, in any script, are enough to count as saying something.
# The fallback for writing systems the other rules cannot read: a script with
# no capitals defeats `_names_something`, and one written without spaces
# defeats any count of words. Set so Whisper's pleasantries stay under it
# ("Thanks for watching!" is 18 letters) and a sentence of content clears it.
MINIMUM_LETTERS = 20

# Capitalised by convention wherever it appears, so its capitalisation is no
# evidence the text names anything. Without this, every first-person hook
# reads as containing a proper noun.
ALWAYS_CAPITALISED = frozenset({"I"})

# Latin only, and deliberately: this one feeds the capitalisation check, and
# capitalisation is a property of bicameral scripts. Devanagari, Arabic, Han
# and Hebrew have no capitals to find.
_CASED_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")
# Any script's letters. `[^\W\d_]` is "word character, but not a digit or
# underscore", which under Python's Unicode-by-default `re` is every letter
# in every alphabet.
_ANY_WORD = re.compile(r"[^\W\d_][^\W\d_'’-]*")
_LETTER = re.compile(r"[^\W\d_]")
# A newline ends a sentence as surely as a full stop: frame readings arrive
# as one text card per line, with no terminal punctuation.
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


def has_substance(text: str) -> bool:
    """Whether this transcript or frame reading is worth condensing.

    False only for text that names nothing, counts nothing, and says almost
    nothing — in practice Whisper's own artifacts on silent or musical audio,
    and empty frame readings. True for everything else, including text this
    cannot be sure about.

    Any one of three things is enough to keep it: a named thing, a numeral,
    or enough real words. They are independent on purpose, so that a text
    thin on one count is rescued by another — "1/3 Cup Flour" leans on the
    numerals, "Use Notion" on the name, "do six sets" on neither of those.
    """
    if not text.strip():
        return False
    return _names_something(text) or _counts_something(text) or _says_enough(text)


def _names_something(text: str) -> bool:
    """A capitalised word that is not merely starting a sentence, or a word
    in capitals. A name is strong evidence content is present, because a name
    is what someone types when they come looking for it.

    Latin script only, so this finds nothing in Devanagari or Han prose and
    is not expected to. It is one of three rules precisely so that the
    scripts it cannot read are covered by the others.
    """
    for sentence in _SENTENCE.split(text):
        for position, word in enumerate(_CASED_WORD.findall(sentence)):
            if _bare(word) in ALWAYS_CAPITALISED:
                continue
            if len(word) > 1 and word.isupper():
                return True
            if position > 0 and word[0].isupper():
                return True
    return False


def _counts_something(text: str) -> bool:
    """A numeral: a quantity, a price, a duration, a step number, an oven
    temperature. Digits only — number *words* are not evidence, since "here
    are five fragrances" that names none of them is the emptiest text in the
    vault."""
    return bool(re.search(r"\d", text))


def _says_enough(text: str) -> bool:
    """Enough distinct non-filler words, or failing that enough letters.

    The floor that separates "Thank you." from a real, if terse, instruction
    like "do six sets". It does most of its work through `FILLER` rather than
    through the count: what makes Whisper's outros empty is that every word
    in them is a pleasantry, not that there are only two.

    Counted over every script, with a letter count behind it for those
    written without spaces. This is the only one of the three rules that
    fires at all for a transcript in Devanagari, Han, Arabic or Cyrillic
    prose, so a Latin-only pattern here emptied every one of them — silently,
    and exactly the way this module exists to prevent.
    """
    real = {
        _bare(word).lower()
        for word in _ANY_WORD.findall(text)
        if len(_bare(word)) > 2 and _bare(word).lower() not in FILLER
    }
    if len(real) >= MINIMUM_REAL_WORDS:
        return True
    return len(_LETTER.findall(text)) >= MINIMUM_LETTERS


def _bare(word: str) -> str:
    """A word without its contraction tail, so "I'll" is judged as "I"."""
    return re.split(r"['’]", word)[0]
