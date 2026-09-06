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

import math
import re

from reel_vault.models import SavedReel

# A keyword hit is strong evidence but not proof: the vault filed this reel
# under a name the query used. Scaling coverage by this keeps a full-coverage
# keyword match (0.8) below a near-perfect semantic match while leaving a
# half-coverage one (0.4) above the default 0.30 threshold.
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

# Words that describe the *answer* wanted rather than the *reels* wanted:
# how to present them (list, summarize, grouped by creator) or which to pick
# out from among them (best, worst). "Summarize what my Sales reels said,
# grouped by creator" asks for the whole shelf in a particular shape;
# "Travel plans for Arambol" asks for one reel on it. What is left of a query
# once the shelf's own name, QUERY_NOISE and these are removed is how the two
# are told apart -- see `terms_beyond_the_shelf`.
#
# Kept apart from QUERY_NOISE, which the keyword arm also reads. "creator" is
# noise in "grouped by creator" and a real term in "reels about creator
# monetization"; the keyword arm's coverage should go on counting it, and
# only the shelf-or-topic decision should not.
ANSWER_SHAPE = frozenset(
    """
    list listing lists
    summarize summarise summary summaries overview recap digest rundown
    grouped group grouping sorted sort
    best top worst better favourite favorite
    rank ranked ranking compare compared comparison
    compile compiled compilation
    creator creators author authors
    said say says saying talk talks talked mention mentions mentioned
    cover covers covered discuss discusses discussed
    """.split()
)


def embedding_text(
    caption: str,
    tags: list[str],
    collection: str,
    subcollection: str | None,
    transcript_summary: str = "",
    frame_analysis_summary: str = "",
) -> str:
    """The text a reel is embedded as — its caption, what its video turned out
    to say and show, and the curated metadata it was filed under.

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

    **The order is load-bearing, because the embedder truncates silently.**
    `all-MiniLM-L6-v2` takes 256 word-pieces and sentence-transformers drops
    the rest without a warning. Across the live vault 7 of 33 reels overflow
    that, so whatever sits last in this string is what stops being searchable
    — and with the metadata leading, that was the media summaries, on 2 of
    the 3 overflowing reels that had them. The one thing the media pipeline
    exists to make findable was the first thing thrown away.

    So the caption and the media summaries lead, and the curated metadata
    trails. Not because the metadata matters less, but because it is the part
    that can afford to be cut: the collection, sub-collection and tags are
    matched word-for-word by the keyword arm on their own untruncated text
    (`metadata_text`), and a collection asked for by name is looked up
    directly without any embedding at all. Losing them here costs a reel one
    of three retrieval paths. What a reel said and showed has only this one.
    """
    parts = (
        caption,
        transcript_summary,
        frame_analysis_summary,
        collection,
        subcollection or "",
        " ".join(tags),
    )
    return " | ".join(part.strip() for part in parts if part.strip())


def embedding_text_for(
    reel: SavedReel,
    collection: str | None = None,
    subcollection: str | None = None,
) -> str:
    """What an already-saved reel should be embedded as, optionally as if it
    sat on a different shelf.

    The one place a stored reel is turned into embedding text. Everything
    except the shelf comes from the reel, so a move cannot quietly drop the
    transcript it had already earned -- which is exactly what re-deriving the
    text from the caption alone would do.

    It exists as a function rather than a method on `Vault` because the
    repair scripts need it too, and the three of them spelling
    `embedding_text`'s arguments out for themselves is how a new embedded
    field ends up reaching live reels and not backfilled ones.

    Passing `collection` also decides `subcollection`: a move sets both, and
    a sub-collection belongs to the shelf it was named under, so carrying the
    old one across would file the reel under a pairing that never existed.
    """
    if collection is None:
        collection, subcollection = reel.collection, reel.subcollection
    return embedding_text(
        reel.caption,
        reel.tags,
        collection,
        subcollection,
        reel.transcript_summary,
        reel.frame_analysis_summary,
    )


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


def terms_beyond_the_shelf(query: str, collection: str) -> list[str]:
    """The words of a query that ask for something more specific than the
    shelf it named.

    A query that names a collection is one of two things, and the vault used
    to treat both as the first. "Show me my Travel reels" wants the shelf.
    "Travel plans for Arambol" wants one reel on it -- and answering it with
    the whole shelf, as happened live, hands over the haystack and calls it
    the needle.

    What tells them apart is what is left once the shelf's own name, the
    framing noise and the answer-shape words are taken away. Nothing left
    means the shelf was the whole request. Anything left is a topic, and the
    shelf's reels should be ranked against it.

    The shelf's name is removed word by word, so "my strength reels" names a
    shelf called "Strength Training" and leaves nothing behind. No stemming:
    a query saying "sale" for a shelf called "Sales" leaves "sale" over and
    is ranked rather than browsed. The caller falls back to the ordinary
    search when a ranking comes up empty, and that search's keyword arm does
    stem -- so the cost is a detour, not the answer.
    """
    shelf = {word.casefold() for word in _WORD.findall(collection)}
    return [
        term
        for term in search_terms(query)
        if term not in shelf and term not in ANSWER_SHAPE
    ]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def rank_within_shelf(
    reels: list[SavedReel],
    query_embedding: list[float],
    threshold: float,
    top_k: int,
) -> list[SavedReel]:
    """One shelf's reels, ranked by how well each answers the query, cut at
    the relevance floor and capped.

    Ranked here rather than by the store's search because that search ranks
    the whole vault and cuts at `top_k` before any shelf filter could apply:
    a shelf of forty reels sitting behind fifty more similar-looking reels
    elsewhere would come back empty. A shelf is small enough to hold whole,
    so ranking it in memory means no reel on it can be crowded out by the
    rest of the vault.

    Cosine on the stored embeddings, without the keyword arm. Every reel on
    the shelf carries the shelf's name, so that arm would score them all
    alike on it, and what remains of the query is prose, best matched by
    meaning. A sub-collection named in the query still counts, because the
    sub-collection is part of what each reel is embedded as.
    """
    scored = [
        (reel, cosine_similarity(query_embedding, reel.embedding)) for reel in reels
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [reel for reel, score in scored[:top_k] if score >= threshold]


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
