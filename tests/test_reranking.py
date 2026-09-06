"""Reading the shortlist instead of trusting the score that produced it.

Three questions asked against the real vault on 2026-09-06, with the cosine
similarities they actually scored. Every one of them was answered wrongly,
and none of the three is a bug in the ranking code -- the arithmetic was
right each time. They are the three ways similarity is the wrong instrument
for deciding which saved video answers a question:

    "Which of my Strength Training reels is about actual training technique,
     not just motivation?"
        0.401  Low Volume High Intensity   <- the one reel that teaches any
        0.400  Biceps                      <- caption is "Youtube: dbrev" + tags
        0.350  30s Fitness Blueprint       <- "Build strength. Get conditioned."
    All three cleared the 0.30 floor and all three came back. A caption with
    no content in it scored level with the answer.

    "Which of my Travel reels is about trekking, not a beach day?"
        0.307  Trekking Maps               <- about paper maps, and the answer given
        0.293  Arambol                     <- the beach day the question excluded
        0.176  Trekking                    <- the actual trek, cut by the floor
    The floor did not merely fail to rank the right reel first. It removed it.

    "Which of my Cooking reels is a snack, not a full meal?"
        0.404  Steak Sandwiches            <- a full meal, ranked top
        0.396  Chakna                      <- tagged `snack` in the database
    The reel the vault itself had labelled a snack was outscored by a meal.

What unites them is that the wanted half and the unwanted half of each
question are about the same subject, so an embedding of the whole sentence
carries "not motivation" as more words about motivation. No threshold
separates those, because the difference is not one of degree.

So similarity became the shortlister and a reranker became the judge. These
tests are about what the vault does with that judgement -- that it is asked
for only when it can change something, that a shortlist reaching below the
old floor is what makes the trek reel reachable at all, and above everything
else that a reranker which is absent, broken or unparseable leaves retrieval
exactly as good as it was without one.
"""

from __future__ import annotations

from dataclasses import replace

from reel_vault.models import (
    CollectionAssignment,
    ExtractedPost,
    ListAnswer,
    NoMatch,
    QueryClassification,
    QueryKind,
    Saved,
    SingleItemAnswer,
)
from tests.conftest import make_vault
from tests.fakes import FakeQueryIntent, FakeReranker, InMemoryReelStore

# The Travel shelf as it really stands, captions trimmed to their first line.
TREK = "https://instagram.com/reel/trek"
MAPS = "https://instagram.com/reel/maps"
BEACH = "https://instagram.com/reel/beach"
BICEPS = "https://instagram.com/reel/biceps"

POSTS = {
    TREK: ExtractedPost(
        caption="Bandaje Arbi Falls Trek. Location: Chikmagalur district",
        author_handle="missing_linkk",
    ),
    MAPS: ExtractedPost(
        caption=(
            "Survey of India maps are till date the best trekking maps available"
        ),
        author_handle="askmanav",
    ),
    BEACH: ExtractedPost(
        caption="How to spend an amazing day in Goa's Arambol",
        author_handle="sonalpaladini",
    ),
    BICEPS: ExtractedPost(
        caption="4 bicep hacks to fix small arms",
        author_handle="supacoopaaa",
    ),
}
ASSIGNMENTS = {
    POSTS[TREK].caption: CollectionAssignment(collection="Travel"),
    POSTS[MAPS].caption: CollectionAssignment(collection="Travel"),
    POSTS[BEACH].caption: CollectionAssignment(collection="Travel"),
    POSTS[BICEPS].caption: CollectionAssignment(collection="Fitness"),
}

TREKKING_QUESTION = "Which of my Travel reels is about trekking, not a beach day?"


def _vault(query: str, kind: QueryKind, collection: str | None, **overrides):
    store = InMemoryReelStore()
    vault = make_vault(
        captions=POSTS,
        assignments=ASSIGNMENTS,
        store=store,
        query_intent=FakeQueryIntent(
            classifications={
                query: QueryClassification(kind=kind, collection=collection)
            }
        ),
        **overrides,
    )
    for url in POSTS:
        assert isinstance(vault.save_reel(url), Saved)
    return vault, store


def _saved(url: str) -> str:
    """The normalized form the vault stores, from the /reel/ form shared."""
    return url.replace("/reel/", "/p/")


# --- the failure that a reranker alone would not have fixed ------------------


def test_a_reel_the_relevance_floor_would_have_hidden_is_still_reachable() -> None:
    """The trek reel scored 0.176 on a question about trekking. Reranking a
    shortlist it had already been cut from would have changed nothing, so
    within a shelf the floor is not applied at all -- the shelf is a filter
    the user named, and everything on it is a reel they chose to keep there.

    The threshold here is set where nothing on the shelf can clear it, which
    is the same situation the live 0.30 produced for this reel, only without
    depending on the fake embedder scoring the way the real one did.
    """
    reranker = FakeReranker(["Bandaje"])
    vault, _ = _vault(
        TREKKING_QUESTION,
        QueryKind.LIST,
        "Travel",
        reranker=reranker,
        match_threshold=0.99,
    )

    answer = vault.ask(TREKKING_QUESTION)

    assert isinstance(answer, ListAnswer)
    assert [reel.url for reel in answer.reels] == [_saved(TREK)]
    # It was asked about the whole shelf, not about what the floor left.
    _, sources = reranker.calls[0]
    assert len(sources) == 3


def test_without_a_reranker_the_relevance_floor_is_still_the_whole_judgement() -> None:
    """The guard on every change here: a vault with no reranker configured
    retrieves exactly as it did before there was one. Same setup as above,
    and the shelf answers nothing, because the floor removes it all."""
    vault, _ = _vault(
        TREKKING_QUESTION, QueryKind.LIST, "Travel", match_threshold=0.99
    )

    assert isinstance(vault.ask(TREKKING_QUESTION), NoMatch)


# --- the judgement itself ----------------------------------------------------


def test_the_reranker_decides_which_reel_answers_a_single_question() -> None:
    """A SINGLE question is answered with `matches[0]`, so the top similarity
    score *was* the answer, unread by anything.

    This query reproduces the live shape in miniature: the maps reel scores
    0.321 and the reel actually asked for scores 0.234, so similarity puts
    the excluded half of the question first. Both clear the shortlist, and
    the judgement is what reorders them.
    """
    query = "the Bandaje falls reel, not the trekking maps one"
    reranker = FakeReranker(["Bandaje", "Survey of India"])
    judged, _ = _vault(query, QueryKind.SINGLE, None, reranker=reranker)
    unjudged, _ = _vault(query, QueryKind.SINGLE, None)

    answer = judged.ask(query)
    without = unjudged.ask(query)

    assert isinstance(answer, SingleItemAnswer)
    assert isinstance(without, SingleItemAnswer)
    # The wrong reel is what similarity alone answers with; that is the bug.
    assert without.reel.url == _saved(MAPS)
    assert answer.reel.url == _saved(TREK)


def test_the_reranker_reads_what_the_video_said_and_showed() -> None:
    """It is asked to judge on content, so it has to be given the content.
    A caption-only view would leave it deciding on exactly the text that
    misled the shortlist -- and "Youtube: dbrev" is a caption whose reel may
    still have taught something out loud."""
    query = "Travel reels about trekking, not a beach day"
    reranker = FakeReranker()
    vault, store = _vault(query, QueryKind.LIST, "Travel", reranker=reranker)
    reel = store.find_by_url(_saved(TREK))
    assert reel is not None
    store.update(
        replace(
            reel,
            transcript_summary="Start the climb at dawn. Carry two litres.",
            frame_analysis_summary="Waterfall at the summit, rope section.",
        )
    )

    vault.ask(query)

    _, sources = reranker.calls[0]
    trekking = next(s for s in sources if "Bandaje" in s.caption)
    assert trekking.transcript == "Start the climb at dawn. Carry two litres."
    assert trekking.frame_text == "Waterfall at the summit, rope section."


def test_nothing_on_the_shelf_answering_falls_through_to_the_whole_vault() -> None:
    """An empty verdict is a real answer -- these were read and none of them
    address the question -- but it is a verdict about one shelf. The reel
    asked about may simply not be where the user thought, and plain search is
    still owed a look before the vault says it has nothing."""
    query = "Travel reels about bicep hacks for small arms"
    # Nothing on the Travel shelf matches this marker, so the shelf is judged
    # to answer nothing; the bicep reel, filed under Fitness, is only reachable
    # on the second pass.
    reranker = FakeReranker(["bicep"])
    vault, _ = _vault(query, QueryKind.LIST, "Travel", reranker=reranker)

    answer = vault.ask(query)

    assert isinstance(answer, ListAnswer)
    assert answer.collection is None
    assert [reel.url for reel in answer.reels] == [_saved(BICEPS)]


# --- what it costs, and what happens when it fails ---------------------------


def test_one_confident_match_is_not_sent_to_be_judged() -> None:
    """This call sits in front of every question asked, so it must not be
    made where it can only agree. One reel, already over the threshold: there
    is no ordering to decide and no second candidate to prefer."""
    query = "the reel about bicep hacks for small arms"
    reranker = FakeReranker()
    # The bicep reel scores 0.365 here and nothing else clears the shortlist.
    vault, _ = _vault(
        query, QueryKind.SINGLE, None, reranker=reranker, match_threshold=0.3
    )

    answer = vault.ask(query)

    assert isinstance(answer, SingleItemAnswer)
    assert answer.reel.url == _saved(BICEPS)
    assert reranker.calls == []


def test_a_lone_half_match_is_judged_rather_than_shown() -> None:
    """The other half of that rule. One candidate that did *not* clear the
    threshold is exactly the case worth paying for: the question is whether
    the thing similarity half-recognised belongs in front of the user at
    all."""
    query = "the reel about bicep hacks for small arms"
    reranker = FakeReranker(["nothing here says this"])
    vault, _ = _vault(
        query, QueryKind.SINGLE, None, reranker=reranker, match_threshold=0.99
    )

    assert isinstance(vault.ask(query), NoMatch)
    assert len(reranker.calls) == 1


def test_an_empty_verdict_cannot_silence_what_similarity_was_sure_of() -> None:
    """The one place these two signals disagree and the judgement loses.

    Measured on the live vault: asked which Strength Training reels teach
    technique rather than motivation, the same call emptied the shelf on two
    runs of three while the reel that teaches it sat there. An empty verdict
    over reels similarity was confident about is one unstable call away from
    hiding a shelf, and the reels it hides are ones the user cannot then ask
    for -- they are never told they exist. Where similarity was unconvinced
    too, the verdict stands; that case is `NoMatch` either way.
    """
    # Two shortlisted (0.321 and 0.234), one of them over the threshold, and
    # a reranker that rejects both.
    query = "the Bandaje falls reel, not the trekking maps one"
    reranker = FakeReranker(["nothing here says this"])
    vault, _ = _vault(
        query, QueryKind.SINGLE, None, reranker=reranker, match_threshold=0.3
    )

    answer = vault.ask(query)

    assert len(reranker.calls) == 1
    assert isinstance(answer, SingleItemAnswer)
    assert answer.reel.url == _saved(MAPS)


def test_a_reranker_that_raises_leaves_the_answer_as_it_was_without_one() -> None:
    """Retrieval must never be worse for having a reranker configured. A
    judgement that could not be made is not a judgement that nothing
    matched."""
    query = "reels about trekking"
    broken, _ = _vault(
        query, QueryKind.LIST, None, reranker=FakeReranker(raises=True)
    )
    plain, _ = _vault(query, QueryKind.LIST, None)

    broken_answer = broken.ask(query)
    plain_answer = plain.ask(query)

    assert isinstance(broken_answer, ListAnswer)
    assert isinstance(plain_answer, ListAnswer)
    assert [reel.url for reel in broken_answer.reels] == [
        reel.url for reel in plain_answer.reels
    ]


def test_an_index_naming_no_candidate_is_ignored() -> None:
    """`ChatReranker` bounds-checks what the model replies, but the port is
    what any implementation reaches, and one bad index must not become an
    IndexError on the path that answers the user."""
    query = "reels about trekking"
    vault, _ = _vault(query, QueryKind.LIST, None, reranker=_OutOfRangeReranker())

    answer = vault.ask(query)

    assert isinstance(answer, ListAnswer)
    assert len(answer.reels) == 1


class _OutOfRangeReranker:
    """A `Reranker` naming one real candidate and two that do not exist."""

    def rerank(self, query: str, sources: list) -> list[int]:
        return [0, 99, -1]
