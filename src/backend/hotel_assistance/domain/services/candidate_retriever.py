"""Candidate preselection for large filter registries.

A 400+ filter catalog does not fit sensibly into a prompt, so retrieval
answers "which filters might be relevant" and the LLM answers "which of these
the user actually asked for". Retrieval is deliberately allowed to be fuzzy:
the deterministic layers downstream never trust its output.
"""

import math
import re
from collections import Counter
from typing import Protocol

from hotel_assistance.domain.models.candidate_filter import CandidateFilter
from hotel_assistance.domain.models.filter_definition import FilterDefinition
from hotel_assistance.domain.services.filter_registry import FilterRegistry

_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "a", "an", "the", "is", "are", "of", "in", "on", "and", "or", "to",
    "for", "with", "at", "this", "that", "have", "has", "do", "does",
    "i", "we", "my", "our", "me", "would", "like", "want", "need", "please",
}

PHRASE_BONUS = 2.0
"""Added when a term appears verbatim, on top of its rarity weight.

Ranks an exact quote above the same words merely scattered through the message.
"""


class CandidateRetriever(Protocol):
    """Returns the filters most likely to be relevant to a user message."""

    async def retrieve(self, query: str, top_k: int) -> list[CandidateFilter]: ...


def definition_to_text(definition: FilterDefinition) -> str:
    """Render a definition as the text used for matching and embedding.

    Backend provenance in ``source`` is intentionally excluded: it is an
    internal identifier mapping, not something a user would ever phrase.
    """

    parts = [
        f"ID: {definition.id}",
        f"Type: {definition.type}",
        f"Description: {definition.description}",
        f"Aliases: {', '.join(definition.aliases)}",
    ]
    if definition.unit:
        parts.append(f"Unit: {definition.unit}")
    return ". ".join(parts)


class KeywordCandidateRetriever:
    """Deterministic alias/keyword retrieval, weighted by term rarity.

    Two things make naive matching useless on this registry. Summing every
    matching term rewards filters with long descriptions, and treating all
    words alike lets registry boilerplate ("Property offers...") and popular
    concepts ("shower", "lounge") outrank a rare, exact quote such as "square
    meters". So a definition scores by its single strongest matching term, and
    each term is weighted by how few filters in the registry use its words.

    Requires no external service, so it is the fallback when embeddings are
    unavailable and the default in tests.
    """

    def __init__(self, registry: FilterRegistry, phrase_only: bool = False) -> None:
        self._registry = registry
        self._phrase_only = phrase_only
        self._word_weights = self._build_word_weights()

    async def retrieve(self, query: str, top_k: int) -> list[CandidateFilter]:
        needle = query.lower()
        needle_words = set(_WORD_RE.findall(needle)) - _STOPWORDS

        scored: list[CandidateFilter] = []
        for definition in self._registry.list_all():
            score = self._score(definition, needle, needle_words)
            if score > 0:
                scored.append(CandidateFilter(definition=definition, score=score))

        scored.sort(key=lambda item: (item.score, item.definition.id), reverse=True)
        return scored[:top_k]

    def _score(self, definition: FilterDefinition, needle: str, needle_words: set[str]) -> float:
        best = 0.0
        for term in self._terms(definition):
            words = set(_WORD_RE.findall(term)) - _STOPWORDS
            if not words:
                continue
            weight = sum(self._word_weights.get(word, 0.0) for word in words)

            if term in needle:
                best = max(best, PHRASE_BONUS + weight)
            elif not self._phrase_only and words <= needle_words:
                # Every word of the term is somewhere in the message, just not
                # as a contiguous quote.
                best = max(best, weight)
        return best

    def _build_word_weights(self) -> dict[str, float]:
        """Smoothed inverse document frequency of each word in the registry.

        A word used by one filter is strong evidence; one used by two hundred
        is nearly none. The weight stays positive even for a word every filter
        shares, so a match is never scored out of existence entirely.
        """

        counts: Counter[str] = Counter()
        for definition in self._registry.list_all():
            words: set[str] = set()
            for term in self._terms(definition):
                words |= set(_WORD_RE.findall(term))
            counts.update(words - _STOPWORDS)

        total = max(len(self._registry), 1)
        return {word: math.log(1 + total / count) for word, count in counts.items()}

    @staticmethod
    def _terms(definition: FilterDefinition) -> list[str]:
        return [
            definition.id.lower(),
            definition.description.lower(),
            *(alias.lower() for alias in definition.aliases),
        ]
