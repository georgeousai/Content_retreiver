"""Why `DEFAULT_MATCH_THRESHOLD` is 0.30, not 0.35.

The evidence behind this is an evaluation, not a unit test in the usual
sense: 17 realistic, hand-phrased queries and 6 adversarial ones ("how do I
fix a flat tire"), run against the real local embedder and the real
`PostgresReelStore.search` on the live vault's 33 reels on 2026-09-01.

    threshold 0.35:  16/17 real queries succeed,  0/6 false matches
    threshold 0.32:  17/17 real queries succeed,  0/6 false matches
    threshold 0.30:  17/17 real queries succeed,  0/6 false matches
    threshold 0.28:  17/17 real queries succeed,  0/6 false matches

The one miss at 0.35 was "how does a RAG pipeline work" against a reel
explaining RAG vs CAG, which scored 0.326 -- just under. The adversarial
queries never exceeded 0.198 at any threshold tested, so 0.30 leaves a
0.10+ margin above the noisiest wrong answer actually measured. That full
evaluation depended on the live vault's current 33 reels and cannot be
re-run automatically here without it drifting as reels are added, moved, or
re-embedded -- see `.scratch/reel-vault-media-pipeline/STATUS.md` for the
complete numbers.

What *can* be pinned without depending on a database that will keep
changing is the one case that actually failed: the two real reels involved,
frozen verbatim, embedded through the real local model (`LocalEmbedder`,
not the bag-of-words fake the rest of the suite uses, because the whole
question is whether the real model's similarity score clears a real
threshold) and the real `embedding_text` assembly. If a future change to
either regresses this specific case, this is where it will be caught.

Loads the actual `all-MiniLM-L6-v2` model. No network call and no database:
the model is local, and everything else here is a frozen string.
"""

from __future__ import annotations

import pytest

from reel_vault.search import embedding_text
from reel_vault.vault import DEFAULT_MATCH_THRESHOLD

# Verbatim from the live vault, 2026-09-01: https://instagram.com/p/DcoQRJKguIZ
# (@bashi_fuirkashi). The reel the miss was about.
RAG_VS_CAG_CAPTION = (
    "RAG vs CAG explained \U0001f447\n\n"
    "Most people learning AI engineering know RAG.\n\n"
    "But CAG, Cache Augmented Generation, is another approach you should "
    "understand.\n\n"
    "With RAG:\n\n"
    "→ Documents are chunked\n→ Chunks are turned into embeddings\n"
    "→ Embeddings are stored in a vector database\n"
    "→ A user query is embedded\n→ Similar chunks are retrieved\n"
    "→ The LLM generates an answer using that retrieved context\n\n"
    "With CAG:\n\n"
    "→ You preload the documents directly into the model’s context\n"
    "→ The model creates a KV cache\n"
    "→ User queries are added to that context\n"
    "→ The LLM answers using the information already loaded\n\n"
    "Sounds simpler, but CAG has tradeoffs.\n\n"
    "You still have to think about:\n\n"
    "⚙️ Context window limits\n⚙️ Scalability\n⚙️ Cost\n"
    "⚙️ Latency\n⚙️ Accuracy\n⚙️ Data freshness\n\n"
    "Knowing how to build a RAG demo is one thing.\n\n"
    "Knowing when to use RAG, CAG, or another retrieval architecture is what "
    "starts moving you toward production-level AI engineering.\n\n"
    "Comment “CAG” and I’ll DM you the link to my AI engineering "
    "community with:\n\n"
    "✅ A full AI engineering learning roadmap\n"
    "✅ Daily calls with working AI/ML engineers\n"
    "✅ Recruiter and career guidance\n"
    "✅ Projects, interview prep, and everything you need to work toward "
    "landing a $150K+ AI engineering role"
)
RAG_VS_CAG_TAGS = ["ai engineering", "retrieval architecture", "cag", "rag", "career guidance"]
RAG_VS_CAG_TRANSCRIPT_SUMMARY = (
    "RAG works by chunking documents into sections, turning chunks into "
    "embeddings, storing embeddings in a vector database. Similarity search "
    "retrieves relevant chunks for a question embedding, LLM generates "
    "response. CAG preloads all documents into the model's KV cache, "
    "allowing the LLM to answer questions with accurate context. CAG is "
    "limited by the model's context window size. Consider scalability, "
    "cost, latency, accuracy, data freshness. Join AI engineering "
    "community: full learning roadmap, daily calls with working AI "
    "engineers, machine learning engineers, recruiters, everything you "
    "need to lend $150,000 plus AI engineering role. Comment CAG and I'll "
    "DM you the link."
)
# This still carries the vision prompt's old fabrication ("over $200,000" for
# a DoorDash offer post that actually read "Base: 145k...") because it was
# analyzed before that prompt was fixed, and existing frame analyses are not
# retroactively redone. Left verbatim, since it is the real production value
# this test exists to check retrieval against -- fixing it is a separate,
# not-yet-done repair (re-run frame analysis on reels saved before the
# vision-prompt fix), tracked in STATUS.md, not this test.
RAG_VS_CAG_FRAME_SUMMARY = (
    "RAG = retrieval augmented generation.  \n"
    "CAG = cache augmented generation.  \n"
    "DoorDash offer: Seattle marketplace consumer platform team, "
    "compensation over $200,000, start October.  \n"
    "Job tracker built with Claude Cowork and MCPs.  \n"
    "AMA session covered AI vs ML roles, AI careers and required skills, "
    "AI/ML interview cycle, interview preparation, common interview "
    "questions."
)

# Verbatim from the live vault, 2026-09-01: https://instagram.com/p/Dciv8ngjAZT
# (@qconconferences). The reel that outranked it -- also a legitimate answer
# to the same query, which is *why* the miss happened: two good answers to
# one broad question split the similarity mass between them.
QCON_CAPTION = (
    "The common argument for scaling RAG is that you can always add more "
    "documents and chunking strategies. \n\n"
    "A December 2024 Google paper challenges that assumption. It found a "
    "mathematical ceiling: once you bring more than 50,000 similar "
    "documents into a RAG pipeline, the dense vector space runs out of "
    "room to represent fine-grained differences.\n\n"
    "The embedding is statistical, not truly semantic, and at enough "
    "document density it collapses distinctions that matter.\n\n"
    "More sessions like this are lined up for QCon AI New York 2026 "
    "(Dec 15-16). Link in bio for more details."
)
QCON_TAGS = ["rag", "vector-space", "google-paper", "qcon-ai", "embedding"]

QUERY = "how does a RAG pipeline work"

# The noisiest wrong answer across 6 adversarial queries in the full
# evaluation. Nothing in this vault should score anywhere near this for
# something the vault has no content about at all.
ADVERSARIAL_QUERY = "how do I fix a flat tire on my car"
MEASURED_NOISE_CEILING = 0.198


@pytest.fixture(scope="module")
def embedder():
    from reel_vault.adapters.embedder import LocalEmbedder

    return LocalEmbedder()


def _similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity. A plain dot product is correct here because
    `LocalEmbedder.embed` asks sentence-transformers to L2-normalize, which
    is also why `PostgresReelStore._vector_search`'s `1 - (embedding <=>
    query)` and this compute the same number without either one needing to
    know the other exists."""
    return sum(x * y for x, y in zip(a, b))


def test_the_query_that_missed_now_clears_the_threshold(embedder) -> None:
    """The regression this file exists to catch. If this drops back under
    `DEFAULT_MATCH_THRESHOLD`, either the threshold moved back up or
    something about how this reel is embedded changed for the worse."""
    text = embedding_text(
        RAG_VS_CAG_CAPTION,
        RAG_VS_CAG_TAGS,
        "AI",
        "RAG",
        RAG_VS_CAG_TRANSCRIPT_SUMMARY,
        RAG_VS_CAG_FRAME_SUMMARY,
    )
    score = _similarity(embedder.embed(QUERY), embedder.embed(text))

    assert score >= DEFAULT_MATCH_THRESHOLD, (
        f"scored {score:.3f}; measured 0.326 in the live vault against a "
        f"0.35 threshold, which is why the threshold moved to 0.30"
    )


def test_the_reel_that_outranked_it_is_also_legitimate(embedder) -> None:
    """The other half of why this was a near-miss and not a broken query:
    the top-ranked result for the same question was a *different* real
    answer, not noise. Confirms the miss was two good answers splitting the
    similarity mass, not the model failing to understand the question."""
    text = embedding_text(QCON_CAPTION, QCON_TAGS, "AI", "RAG")
    score = _similarity(embedder.embed(QUERY), embedder.embed(text))

    assert score >= DEFAULT_MATCH_THRESHOLD


def test_lowering_the_threshold_does_not_let_the_wrong_reel_through(embedder) -> None:
    """The safety check the recommendation depended on. A lower threshold is
    only safe if nothing irrelevant sneaks in under it -- measured, on the
    full evaluation, as a 0.198 ceiling across 6 topics this vault has
    nothing about. Checked here against the two reels actually in this file,
    with headroom: a real regression would have to be dramatic to reach
    `DEFAULT_MATCH_THRESHOLD` from either reel's true topic."""
    query_embedding = embedder.embed(ADVERSARIAL_QUERY)

    for caption, tags in [
        (RAG_VS_CAG_CAPTION, RAG_VS_CAG_TAGS),
        (QCON_CAPTION, QCON_TAGS),
    ]:
        text = embedding_text(caption, tags, "AI", "RAG")
        score = _similarity(query_embedding, embedder.embed(text))
        assert score < DEFAULT_MATCH_THRESHOLD
        assert score < MEASURED_NOISE_CEILING + 0.1, (
            "a flat-tire question is scoring close to real vault noise -- "
            "re-run the full adversarial evaluation before trusting this "
            "threshold"
        )


def test_the_threshold_is_where_this_file_says_it_is() -> None:
    """So a change to the constant is caught here, at the evidence, rather
    than only showing up as a mysterious search regression somewhere else."""
    assert DEFAULT_MATCH_THRESHOLD == 0.30
