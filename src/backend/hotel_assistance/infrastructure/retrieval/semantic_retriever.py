"""Embedding-based candidate retrieval with an on-disk index cache.

Only the user's message is embedded per request; the registry itself is
embedded once and cached, keyed by a fingerprint of the registry contents and
the embedding model, so any registry edit invalidates the cache automatically.
"""

import asyncio
import hashlib
import json
import logging
import math
import time
from pathlib import Path

from hotel_assistance.domain.models.candidate_filter import CandidateFilter
from hotel_assistance.domain.services.candidate_retriever import definition_to_text
from hotel_assistance.domain.services.filter_registry import FilterRegistry
from hotel_assistance.infrastructure.embeddings.provider import EmbeddingProvider

logger = logging.getLogger(__name__)


class SemanticCandidateRetriever:
    """Ranks registry filters by cosine similarity to the user's message."""

    def __init__(
        self,
        registry: FilterRegistry,
        embedding_provider: EmbeddingProvider,
        cache_path: str | Path,
        embedding_model_name: str,
    ) -> None:
        self._registry = registry
        self._embedding_provider = embedding_provider
        self._cache_path = Path(cache_path)
        self._embedding_model_name = embedding_model_name
        self._index: list[list[float]] | None = None
        self._index_lock = asyncio.Lock()

    async def retrieve(self, query: str, top_k: int) -> list[CandidateFilter]:
        started = time.perf_counter()
        index = await self._ensure_index()
        query_embedding = (await self._embedding_provider.embed([query]))[0]

        scored = [
            CandidateFilter(definition=definition, score=_cosine_similarity(query_embedding, embedding))
            for definition, embedding in zip(self._registry.list_all(), index, strict=True)
        ]
        scored.sort(key=lambda item: item.score, reverse=True)
        top = scored[:top_k]

        logger.info(
            "semantic retrieval: top_k=%d elapsed_ms=%.1f best=%s",
            top_k,
            (time.perf_counter() - started) * 1000,
            [(item.definition.id, round(item.score, 4)) for item in top[:5]],
        )
        return top

    async def _ensure_index(self) -> list[list[float]]:
        # The index is built once per process; the lock keeps concurrent first
        # requests from each paying for a full-registry embedding run.
        async with self._index_lock:
            if self._index is None:
                self._index = await self._load_or_build_index()
            return self._index

    async def _load_or_build_index(self) -> list[list[float]]:
        fingerprint = self._registry_fingerprint()
        cached = self._read_cache()
        if (
            cached is not None
            and cached.get("fingerprint") == fingerprint
            and cached.get("embedding_model") == self._embedding_model_name
            and len(cached.get("embeddings", [])) == len(self._registry)
        ):
            logger.info("embedding index: cache hit (%s)", self._cache_path)
            return cached["embeddings"]

        logger.info("embedding index: rebuilding %d filters (%s)", len(self._registry), self._cache_path)
        embeddings = await self._embedding_provider.embed(
            [definition_to_text(definition) for definition in self._registry.list_all()]
        )
        self._write_cache(fingerprint, embeddings)
        return embeddings

    def _read_cache(self) -> dict | None:
        if not self._cache_path.exists():
            return None
        try:
            return json.loads(self._cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            # A damaged cache is a performance problem, not a correctness one.
            logger.warning("embedding index: ignoring unreadable cache %s (%s)", self._cache_path, exc)
            return None

    def _write_cache(self, fingerprint: str, embeddings: list[list[float]]) -> None:
        payload = {
            "fingerprint": fingerprint,
            "embedding_model": self._embedding_model_name,
            "embeddings": embeddings,
        }
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(json.dumps(payload), encoding="utf-8")
        except OSError as exc:
            logger.warning("embedding index: could not write cache %s (%s)", self._cache_path, exc)

    def _registry_fingerprint(self) -> str:
        payload = [definition_to_text(definition) for definition in self._registry.list_all()]
        raw = json.dumps(payload, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    dot = sum(x * y for x, y in zip(left, right, strict=True))
    norm_left = math.sqrt(sum(x * x for x in left))
    norm_right = math.sqrt(sum(x * x for x in right))
    if norm_left == 0 or norm_right == 0:
        return 0.0
    return dot / (norm_left * norm_right)
