from __future__ import annotations

import pytest

from reel_vault.vault import Vault
from tests.fakes import (
    FakeCaptionFetcher,
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
    captions: dict[str, str | None] | None = None,
    tags_by_caption: dict[str, list[str]] | None = None,
    store: InMemoryReelStore | None = None,
    aggregate_triggers: tuple[str, ...] = ("all", "summarize", "every"),
    match_threshold: float = 0.1,
) -> Vault:
    return Vault(
        caption_fetcher=FakeCaptionFetcher(captions or {}),
        tagger=FakeTagger(tags_by_caption),
        embedder=FakeEmbedder(),
        store=store if store is not None else InMemoryReelStore(),
        query_intent=FakeQueryIntent(aggregate_triggers),
        summarizer=FakeSummarizer(),
        match_threshold=match_threshold,
    )
