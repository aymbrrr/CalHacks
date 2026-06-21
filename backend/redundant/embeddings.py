"""Embeddings via OpenAI text-embedding-3-small (1536 dims).

A tiny in-process LRU avoids re-embedding identical normalized inputs within a
process. If no OpenAI key is configured, a deterministic local fallback embedding
is used so tests and offline demos still exercise the vector path.
"""

from __future__ import annotations

import hashlib
import math
from functools import lru_cache

from redundant.config import SETTINGS, Settings

_client = None


def _get_client(settings: Settings):
    global _client
    if _client is None:
        from openai import OpenAI

        _client = OpenAI(api_key=settings.openai_api_key)
    return _client


def _local_fallback_embedding(text: str, dim: int) -> list[float]:
    """Deterministic pseudo-embedding from a hash, L2-normalized.

    Not semantically meaningful across unrelated text, but stable: identical text
    yields an identical vector (cosine 1.0), which keeps the vector plumbing
    testable without network access.
    """
    vec = [0.0] * dim
    seed = hashlib.sha256(text.encode("utf-8")).digest()
    # Spread hash bytes across the vector deterministically.
    for i in range(dim):
        b = seed[i % len(seed)]
        vec[i] = ((b / 255.0) * 2.0 - 1.0) * (1.0 / (1 + (i % 7)))
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


@lru_cache(maxsize=2048)
def embed(text: str, settings: Settings = SETTINGS) -> tuple[float, ...]:
    # Offline by request or when no key is configured: deterministic local vector.
    if settings.embeddings_offline or not settings.openai_api_key:
        return tuple(_local_fallback_embedding(text, settings.embedding_dim))
    try:
        client = _get_client(settings)
        resp = client.embeddings.create(model=settings.embedding_model, input=text)
        return tuple(resp.data[0].embedding)
    except Exception:
        # An embedding outage (bad key, no network, rate limit) must never crash
        # the firewall or block the demo. Degrade to the deterministic local
        # vector (same dim) so the vector path keeps working.
        return tuple(_local_fallback_embedding(text, settings.embedding_dim))


def embed_list(text: str, settings: Settings = SETTINGS) -> list[float]:
    return list(embed(text, settings))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)
