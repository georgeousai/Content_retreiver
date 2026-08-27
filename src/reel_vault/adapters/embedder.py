"""Local, CPU-only embedding via sentence-transformers — no external API call."""

from __future__ import annotations

DEFAULT_MODEL_NAME = "all-MiniLM-L6-v2"


class LocalEmbedder:
    def __init__(self, *, model_name: str = DEFAULT_MODEL_NAME) -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name, device="cpu")

    def embed(self, text: str) -> list[float]:
        vector = self._model.encode(text, normalize_embeddings=True)
        return vector.tolist()
