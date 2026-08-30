"""What a reel looks like to the retriever, and what a query contributes to it.

Retrieval has two arms, because a reel carries two very different kinds of
text. The caption is free-form prose the creator wrote, best matched by
meaning. The collection, sub-collection and tags are a short curated
vocabulary the vault itself assigned, best matched by word.

Both arms read their definitions from this module so that what is indexed
and what is searched can never come to describe different things — the same
drift that let the URL matcher and the dedup key disagree (see
.scratch/known-issues.md).
"""

from __future__ import annotations

import re

from reel_vault.models import SavedReel

# A keyword hit is strong evidence but not proof: the vault filed this reel
# under a name the query used. Scaling coverage by this keeps a full-coverage
# keyword match (0.8) below a near-perfect semantic match while leaving a
# half-coverage one (0.4) above the default 0.35 threshold.
KEYWORD_WEIGHT = 0.8

# Words that say nothing about *which* reels are wanted. Every saved item is
# a reel, so "reel" selects everything; the framing verbs and possessives are
# addressed to the bot rather than to the vault's contents. These are removed
# before coverage is computed — left in, "show me my interview reels" would
# score 1 matched term out of 5 and fall under the threshold on phrasing
# alone.
QUERY_NOISE = frozenset(
    """
    reel reels video videos post posts clip clips content
    show find get give tell fetch pull bring look see want need
    saved save vault collection collections
    a an the my me mine i you your we our
    of on in for to at by with from about into over
    that this these those it its there here
    all any some every each both few more most other
    is are was were be been being am do does did doing done
    have has had having can could will would shall should may might must
    what which who whom whose when where why how
    and or but not no nor so than then too very just
    please again also still yet
    anything something everything nothing anyone someone everyone
    thing things stuff lot lots bunch kind sort ones
    """.split()
)

_WORD = re.compile(r"[A-Za-z0-9]+")


def embedding_text(
    caption: str,
    tags: list[str],
    collection: str,
    subcollection: str | None,
    transcript_summary: str = "",
    frame_analysis_summary: str = "",
) -> str:
    """The text a reel is embedded as — its curated metadata, its caption, and
    what its video turned out to say and show.

    Caption alone is too thin a signal to retrieve on. A reel filed under
    "Product Management > Interviews", tagged "case prep", scored 0.330
    against "reels about interview prep" — under the match threshold — while
    its own metadata answered the query outright. The metadata often says
    what the caption never does ("Five Year Journey #fyp" is filed under
    Personal Growth > Journey and would otherwise be findable by neither
    word), so it is embedded alongside the caption rather than left to one
    side.

    The media summaries join the same text rather than getting an arm of
    their own. They are free prose like the caption, best matched by meaning,
    and folding them in is what finally makes a comment-bait reel — "comment
    HABITS for my list", nearly half the live vault — findable by what the
    creator actually said out loud. Only the condensed halves belong here:
    embedding a full transcript would swamp the caption and the shelf it sits
    on, and the raw text is kept for regenerating a summary, not for search.
    """
    parts = (
        collection,
        subcollection or "",
        " ".join(tags),
        caption,
        transcript_summary,
        frame_analysis_summary,
    )
    return " | ".join(part.strip() for part in parts if part.strip())


def metadata_text(
    tags: list[str], collection: str, subcollection: str | None
) -> str:
    """The curated half of a reel on its own — what the keyword arm matches.

    The caption is deliberately absent. It is long, free-form, and shares
    words with any query by chance, so including it would let a stray common
    word outrank a reel the vault deliberately filed under the term asked
    for. The keyword arm exists to make the taxonomy retrievable; meaning is
    the other arm's job.
    """
    return " ".join(
        part.strip()
        for part in (collection, subcollection or "", " ".join(tags))
        if part.strip()
    )


def search_terms(query: str) -> list[str]:
    """The words in a query worth matching against curated metadata.

    Framing words are dropped before this returns, because the caller scores
    a reel by *what fraction* of these terms it matched: leaving "show me my
    ... reels" in would dilute every real term's contribution and make a
    reel's score depend on how chattily the question was phrased.

    Reduced to bare alphanumerics, since these terms are handed to Postgres's
    `to_tsquery`, which reads its input as an expression rather than as text.
    """
    terms: dict[str, None] = {}
    for word in _WORD.findall(query):
        folded = word.casefold()
        if len(folded) > 1 and folded not in QUERY_NOISE:
            terms.setdefault(folded, None)
    return list(terms)


def keyword_score(matched_terms: int, total_terms: int) -> float:
    """How strongly a keyword match counts, as a fraction of the query it
    accounts for. Matching one of five terms is a coincidence; matching four
    of five is an answer, and the score has to be able to tell them apart."""
    if total_terms <= 0 or matched_terms <= 0:
        return 0.0
    return KEYWORD_WEIGHT * (matched_terms / total_terms)


def merge_hits(
    vector_hits: list[tuple[SavedReel, float]],
    keyword_hits: list[tuple[SavedReel, float]],
    top_k: int,
) -> list[tuple[SavedReel, float]]:
    """One ranked list from both arms, each reel keeping its better score.

    Deliberately not a sum: a reel that matches by meaning *and* by tag is
    the same reel, and adding the two would push it above a reel that is a
    stronger answer on either count alone. The arms are two ways of asking
    the same question, so the more confident answer wins.
    """
    best: dict[str, tuple[SavedReel, float]] = {}
    for reel, score in [*vector_hits, *keyword_hits]:
        found = best.get(reel.url)
        if found is None or score > found[1]:
            best[reel.url] = (reel, score)
    ranked = sorted(best.values(), key=lambda pair: pair[1], reverse=True)
    return ranked[:top_k]
