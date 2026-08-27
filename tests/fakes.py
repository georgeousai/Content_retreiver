"""Fake adapters for exercising `Vault` without any real network/LLM/DB calls,
per the spec's testing decisions (tests target the seam, not the adapters)."""

from __future__ import annotations

import math

from reel_vault.models import SavedReel
from reel_vault.urls import normalize_reel_url


class FakeCaptionFetcher:
    """Maps URL -> caption. A missing/None entry simulates extraction failure."""

    def __init__(self, captions: dict[str, str | None]) -> None:
        self._captions = captions

    def fetch(self, url: str) -> str | None:
        return self._captions.get(url)


class FakeTagger:
    """Deterministic tagger: splits on a caller-supplied mapping, defaulting
    to a single tag derived from the caption's first word."""

    def __init__(self, tags_by_caption: dict[str, list[str]] | None = None) -> None:
        self._tags_by_caption = tags_by_caption or {}

    def tag(self, caption: str) -> list[str]:
        if caption in self._tags_by_caption:
            return self._tags_by_caption[caption]
        first_word = caption.strip().split()[0].lower() if caption.strip() else "untagged"
        return [first_word]


class FakeEmbedder:
    """Deterministic bag-of-words embedding: cosine similarity between two
    texts reflects shared-word overlap, which is enough to exercise search
    ranking/thresholding without a real model."""

    def __init__(self, dim: int = 64) -> None:
        self._dim = dim

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        for word in text.lower().split():
            vec[hash(word) % self._dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class InMemoryReelStore:
    def __init__(self) -> None:
        self._by_url: dict[str, SavedReel] = {}

    def find_by_url(self, normalized_url: str) -> SavedReel | None:
        return self._by_url.get(normalized_url)

    def save(self, reel: SavedReel) -> None:
        self._by_url[normalize_reel_url(reel.url)] = reel

    def search(
        self, query_embedding: list[float], top_k: int
    ) -> list[tuple[SavedReel, float]]:
        scored = [
            (reel, _cosine(query_embedding, reel.embedding))
            for reel in self._by_url.values()
        ]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:top_k]


class FakeQueryIntent:
    """Aggregate iff the query contains any of a caller-supplied set of
    trigger phrases; defaults to keywords like 'all'/'summarize'."""

    def __init__(self, aggregate_triggers: tuple[str, ...] = ("all", "summarize", "every")) -> None:
        self._triggers = aggregate_triggers

    def is_aggregate(self, query: str) -> bool:
        lowered = query.lower()
        return any(trigger in lowered for trigger in self._triggers)


class FakeSummarizer:
    def summarize(self, query: str, captions: list[str]) -> str:
        return " | ".join(captions)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a)) or 1.0
    norm_b = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (norm_a * norm_b)
