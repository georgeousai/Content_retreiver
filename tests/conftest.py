from __future__ import annotations

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
    captions: dict[str, ExtractedPost | str | None] | None = None,
    tags_by_caption: dict[str, list[str]] | None = None,
    assignments: dict[str, CollectionAssignment] | None = None,
    collection_assigner: FakeCollectionAssigner | None = None,
    store: InMemoryReelStore | None = None,
    aggregate_triggers: tuple[str, ...] = ("all", "summarize", "every"),
    match_threshold: float = 0.1,
) -> Vault:
    return Vault(
        caption_fetcher=FakeCaptionFetcher(captions or {}),
        tagger=FakeTagger(tags_by_caption),
        collection_assigner=(
            collection_assigner
            if collection_assigner is not None
            else FakeCollectionAssigner(assignments)
        ),
        embedder=FakeEmbedder(),
        store=store if store is not None else InMemoryReelStore(),
        query_intent=FakeQueryIntent(aggregate_triggers),
        summarizer=FakeSummarizer(),
        match_threshold=match_threshold,
    )
