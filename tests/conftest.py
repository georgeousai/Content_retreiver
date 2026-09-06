from __future__ import annotations

from collections.abc import Mapping

import pytest

from reel_vault.models import CollectionAssignment, ExtractedPost
from reel_vault.vault import RetrievalSettings, Vault
from tests.fakes import (
    FakeCaptionFetcher,
    FakeCollectionAssigner,
    FakeComparer,
    FakeCondenser,
    FakeEmbedder,
    FakeItemExtractor,
    FakeMediaExtractor,
    FakeQueryIntent,
    FakeSummarizer,
    FakeTagger,
    InMemoryReelStore,
)


@pytest.fixture
def store() -> InMemoryReelStore:
    return InMemoryReelStore()


def make_vault(
    *,
    captions: Mapping[str, ExtractedPost | str | None] | None = None,
    tags_by_caption: dict[str, list[str]] | None = None,
    assignments: dict[str, CollectionAssignment] | None = None,
    collection_assigner: FakeCollectionAssigner | None = None,
    store: InMemoryReelStore | None = None,
    summarizer: FakeSummarizer | None = None,
    comparer: FakeComparer | None = None,
    item_extractor: FakeItemExtractor | None = None,
    media_extractor: FakeMediaExtractor | None = None,
    condenser: FakeCondenser | None = None,
    embedder: FakeEmbedder | None = None,
    query_intent: FakeQueryIntent | None = None,
    aggregate_triggers: tuple[str, ...] = ("give me all", "summarize", "every"),
    match_threshold: float = 0.1,
    **retrieval_overrides: float,
) -> Vault:
    return Vault(
        caption_fetcher=FakeCaptionFetcher(captions or {}),
        tagger=FakeTagger(tags_by_caption),
        collection_assigner=(
            collection_assigner
            if collection_assigner is not None
            else FakeCollectionAssigner(assignments)
        ),
        embedder=embedder if embedder is not None else FakeEmbedder(),
        store=store if store is not None else InMemoryReelStore(),
        query_intent=(
            query_intent
            if query_intent is not None
            else FakeQueryIntent(aggregate_triggers)
        ),
        summarizer=summarizer if summarizer is not None else FakeSummarizer(),
        comparer=comparer if comparer is not None else FakeComparer(),
        item_extractor=(
            item_extractor if item_extractor is not None else FakeItemExtractor()
        ),
        media_extractor=media_extractor,
        # Verbatim by default so a test can assert the video's words are
        # findable without also having to model what condensing did to them.
        condenser=condenser if condenser is not None else FakeCondenser(verbatim=True),
        # Tests name the knobs individually; the vault takes them as one
        # value. Assembled here so a test that cares about one number does
        # not have to build the whole settings object to say so.
        retrieval=RetrievalSettings(
            match_threshold=match_threshold,
            **retrieval_overrides,  # type: ignore[arg-type]
        ),
    )
