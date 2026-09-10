"""Semantic retrieval with a reserved lane for exact alias matches.

Embedding one long message produces a single averaged vector, so a specific
ask buried in a detailed request ("...and at least 30 square meters...") can
rank far outside the top-K even though its alias appears verbatim. Reserving
a few slots for deterministic keyword hits makes those requests reachable
without giving up the semantic layer's ability to match paraphrase.
"""

import asyncio
import logging

from hotel_assistance.domain.models.candidate_filter import CandidateFilter
from hotel_assistance.domain.services.candidate_retriever import CandidateRetriever

logger = logging.getLogger(__name__)

DEFAULT_KEYWORD_QUOTA = 6


class HybridCandidateRetriever:
    def __init__(
        self,
        semantic: CandidateRetriever,
        keyword: CandidateRetriever,
        keyword_quota: int = DEFAULT_KEYWORD_QUOTA,
    ) -> None:
        """``keyword`` should be precise rather than broad.

        Every slot it claims is one the semantic ranking loses, so pass a
        retriever that only reports verbatim matches.
        """

        self._semantic = semantic
        self._keyword = keyword
        self._keyword_quota = keyword_quota

    async def retrieve(self, query: str, top_k: int) -> list[CandidateFilter]:
        quota = min(self._keyword_quota, top_k)
        semantic, keyword = await asyncio.gather(
            self._semantic.retrieve(query, top_k),
            self._keyword.retrieve(query, quota + top_k),
        )

        semantic_ids = {candidate.definition.id for candidate in semantic}
        keyword_only = [item for item in keyword if item.definition.id not in semantic_ids][:quota]

        # Keyword hits take their slots from the weakest semantic matches, so
        # the candidate list stays within the caller's top_k budget.
        selected = semantic[: max(top_k - len(keyword_only), 0)] + keyword_only
        if keyword_only:
            logger.info(
                "hybrid retrieval: %d keyword-only candidates added (%s)",
                len(keyword_only),
                [item.definition.id for item in keyword_only],
            )
        return selected
