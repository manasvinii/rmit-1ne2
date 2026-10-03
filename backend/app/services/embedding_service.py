"""Text embeddings behind one interface.

- fastembed (default): local ONNX model, no API key, 384-dim BAAI/bge-small-en-v1.5
- openai: text-embedding-3-small truncated to EMBEDDING_DIM
- hash: deterministic bag-of-words hashing; used by tests, no model download
"""

from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from typing import Protocol

import numpy as np

from app.core.config import get_settings


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _normalize(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return m / norms


class HashEmbedder:
    """Deterministic, model-free embedding (token + bigram hashing). Good enough for tests."""

    def __init__(self, dim: int = 384):
        self.dim = dim
        self.name = f"hash-{dim}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            toks = re.findall(r"[a-z0-9]+", t.lower())
            feats = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
            for f in feats:
                h = int(hashlib.md5(f.encode()).hexdigest(), 16)
                out[i, h % self.dim] += 1.0 if (h >> 64) & 1 else -1.0
        return _normalize(out).tolist()


class FastEmbedEmbedder:
    def __init__(self, model: str, dim: int):
        from fastembed import TextEmbedding

        self.model = TextEmbedding(model_name=model)
        self.dim = dim
        self.name = f"fastembed:{model}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vecs = np.asarray(list(self.model.embed(texts, batch_size=32)), dtype=np.float32)
        return _normalize(vecs).tolist()


class OpenAIEmbedder:
    def __init__(self, model: str, dim: int):
        from openai import OpenAI

        s = get_settings()
        self.client = OpenAI(api_key=s.openai_api_key or None, base_url=s.openai_base_url or None)
        self.model = model
        self.dim = dim
        self.name = f"openai:{model}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 256):
            resp = self.client.embeddings.create(
                model=self.model, input=texts[i : i + 256], dimensions=self.dim
            )
            out.extend(d.embedding for d in resp.data)
        return _normalize(np.asarray(out, dtype=np.float32)).tolist()


_override: Embedder | None = None


@lru_cache
def _build() -> Embedder:
    s = get_settings()
    if s.embedding_provider == "hash":
        return HashEmbedder(s.embedding_dim)
    if s.embedding_provider == "openai":
        return OpenAIEmbedder(
            s.embedding_model if "embedding" in s.embedding_model else "text-embedding-3-small",
            s.embedding_dim,
        )
    return FastEmbedEmbedder(s.embedding_model, s.embedding_dim)


def get_embedder() -> Embedder:
    return _override or _build()


def set_embedder(embedder: Embedder | None) -> None:
    global _override
    _override = embedder
