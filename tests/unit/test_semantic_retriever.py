import asyncio
import json

from hotel_assistance.domain.models.filter_definition import FilterDefinition
from hotel_assistance.domain.services.filter_registry import FilterRegistry
from hotel_assistance.infrastructure.retrieval.semantic_retriever import (
    SemanticCandidateRetriever,
)


class FakeEmbeddingProvider:
    """Projects text onto three hand-picked concepts, so ranking is predictable."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [
            [
                1.0 if "soundproof" in text.lower() or "quiet" in text.lower() else 0.0,
                1.0 if "size" in text.lower() or "square meters" in text.lower() else 0.0,
                1.0 if "parking" in text.lower() else 0.0,
            ]
            for text in texts
        ]


def build_registry() -> FilterRegistry:
    return FilterRegistry(
        [
            FilterDefinition(id="room.soundproofing", type="boolean", description="Room has soundproofing"),
            FilterDefinition(id="room.size_m2", type="range", description="Room size", unit="m2"),
            FilterDefinition(id="hotel.parking", type="boolean", description="Property offers parking"),
        ]
    )


def build_retriever(cache_path, provider=None) -> SemanticCandidateRetriever:
    return SemanticCandidateRetriever(
        registry=build_registry(),
        embedding_provider=provider or FakeEmbeddingProvider(),
        cache_path=cache_path,
        embedding_model_name="fake",
    )


def test_retrieve_ranks_semantically_close_filters_first(tmp_path) -> None:
    retriever = build_retriever(tmp_path / "index.json")

    candidates = asyncio.run(retriever.retrieve("a quiet room, at least 30 square meters", top_k=2))

    ids = {candidate.definition.id for candidate in candidates}
    assert ids == {"room.soundproofing", "room.size_m2"}


def test_index_is_cached_on_disk_and_reused(tmp_path) -> None:
    cache_path = tmp_path / "index.json"
    first_provider = FakeEmbeddingProvider()
    asyncio.run(build_retriever(cache_path, first_provider).retrieve("parking", top_k=1))

    assert cache_path.exists()
    assert len(first_provider.calls) == 2  # registry index, then the query

    second_provider = FakeEmbeddingProvider()
    asyncio.run(build_retriever(cache_path, second_provider).retrieve("parking", top_k=1))

    # Only the query is embedded the second time round.
    assert len(second_provider.calls) == 1


def test_cache_is_rebuilt_when_the_registry_changes(tmp_path) -> None:
    cache_path = tmp_path / "index.json"
    asyncio.run(build_retriever(cache_path).retrieve("parking", top_k=1))
    stale = json.loads(cache_path.read_text(encoding="utf-8"))

    larger_registry = FilterRegistry(
        [
            *build_registry().list_all(),
            FilterDefinition(id="hotel.spa", type="boolean", description="Property offers a spa"),
        ]
    )
    retriever = SemanticCandidateRetriever(
        registry=larger_registry,
        embedding_provider=FakeEmbeddingProvider(),
        cache_path=cache_path,
        embedding_model_name="fake",
    )
    asyncio.run(retriever.retrieve("parking", top_k=1))

    rebuilt = json.loads(cache_path.read_text(encoding="utf-8"))
    assert rebuilt["fingerprint"] != stale["fingerprint"]
    assert len(rebuilt["embeddings"]) == 4


def test_unreadable_cache_is_ignored_rather_than_fatal(tmp_path) -> None:
    cache_path = tmp_path / "index.json"
    cache_path.write_text("{ not json", encoding="utf-8")

    candidates = asyncio.run(build_retriever(cache_path).retrieve("parking", top_k=1))

    assert candidates[0].definition.id == "hotel.parking"
