from __future__ import annotations

from collections.abc import Mapping

import pytest

from reel_vault.models import CollectionAssignment, ExtractedPost
from reel_vault.vault import Vault
from tests.fakes import (
    FakeCaptionFetcher,
    FakeCollectionAssigner,
    FakeEmbedder,
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
    embedder: FakeEmbedder | None = None,
    query_intent: FakeQueryIntent | None = None,
    aggregate_triggers: tuple[str, ...] = ("give me all", "summarize", "every"),
    match_threshold: float = 0.1,
    **top_k_overrides: int,
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
        match_threshold=match_threshold,
        **top_k_overrides,
    )
