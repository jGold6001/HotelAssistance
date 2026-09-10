import asyncio

from hotel_assistance.domain.models.candidate_filter import CandidateFilter
from hotel_assistance.domain.models.filter_definition import FilterDefinition
from hotel_assistance.infrastructure.retrieval.hybrid_retriever import (
    HybridCandidateRetriever,
)


def definition(filter_id: str) -> FilterDefinition:
    return FilterDefinition(id=filter_id, type="boolean", description=filter_id)


class StubRetriever:
    def __init__(self, ids: list[str]) -> None:
        self._ids = ids
        self.requested_top_k: int | None = None

    async def retrieve(self, query: str, top_k: int) -> list[CandidateFilter]:
        self.requested_top_k = top_k
        return [
            CandidateFilter(definition=definition(filter_id), score=1.0)
            for filter_id in self._ids[:top_k]
        ]


def retrieve(semantic_ids, keyword_ids, top_k=5, quota=2):
    retriever = HybridCandidateRetriever(
        semantic=StubRetriever(semantic_ids),
        keyword=StubRetriever(keyword_ids),
        keyword_quota=quota,
    )
    return [item.definition.id for item in asyncio.run(retriever.retrieve("query", top_k))]


def test_keyword_only_hits_displace_the_weakest_semantic_matches() -> None:
    result = retrieve(semantic_ids=["s1", "s2", "s3", "s4", "s5"], keyword_ids=["k1", "k2"])

    assert result == ["s1", "s2", "s3", "k1", "k2"]


def test_result_never_exceeds_top_k() -> None:
    result = retrieve(
        semantic_ids=[f"s{index}" for index in range(10)],
        keyword_ids=[f"k{index}" for index in range(10)],
        top_k=5,
        quota=3,
    )

    assert len(result) == 5


def test_duplicates_do_not_consume_the_keyword_quota() -> None:
    result = retrieve(semantic_ids=["s1", "s2", "s3", "s4", "s5"], keyword_ids=["s1", "s2"])

    assert result == ["s1", "s2", "s3", "s4", "s5"]


def test_semantic_ranking_is_preserved() -> None:
    result = retrieve(semantic_ids=["s1", "s2", "s3", "s4", "s5"], keyword_ids=[])

    assert result == ["s1", "s2", "s3", "s4", "s5"]


def test_quota_is_capped_by_top_k() -> None:
    result = retrieve(semantic_ids=["s1"], keyword_ids=["k1", "k2", "k3"], top_k=1, quota=3)

    assert result == ["k1"]
