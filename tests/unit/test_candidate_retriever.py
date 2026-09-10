import asyncio

from hotel_assistance.domain.models.filter_definition import FilterDefinition
from hotel_assistance.domain.services.candidate_retriever import (
    KeywordCandidateRetriever,
    definition_to_text,
)
from hotel_assistance.domain.services.filter_registry import FilterRegistry


def retrieve(registry: FilterRegistry, query: str, top_k: int = 20, phrase_only: bool = False):
    retriever = KeywordCandidateRetriever(registry, phrase_only=phrase_only)
    return asyncio.run(retriever.retrieve(query, top_k))


def test_finds_filters_by_alias() -> None:
    candidates = retrieve(FilterRegistry.default(), "I need free parking and a swimming pool")

    ids = {candidate.definition.id for candidate in candidates}
    assert "hotel.parking" in ids
    assert "hotel.swimming_pool" in ids


def test_a_rare_exact_phrase_outranks_a_popular_word() -> None:
    """"square meters" identifies one filter; "shower" is shared by a dozen."""

    candidates = retrieve(
        FilterRegistry.default(),
        "the room should be at least 30 square meters, and I would love a rain shower",
        phrase_only=True,
    )

    ids = [candidate.definition.id for candidate in candidates]
    assert ids[0] == "room.size_m2"


def test_registry_boilerplate_does_not_match_everything() -> None:
    """Nearly every description starts with "Property offers" or "Room has"."""

    candidates = retrieve(FilterRegistry.default(), "tell me about this property room")

    assert len(candidates) < 20


def test_phrase_only_mode_ignores_scattered_words() -> None:
    registry = FilterRegistry(
        [FilterDefinition(id="hotel.airport_shuttle_free", type="boolean", description="Free airport shuttle")]
    )
    query = "is the shuttle from the airport free"

    assert retrieve(registry, query) != []
    assert retrieve(registry, query, phrase_only=True) == []


def test_verbatim_quotes_outrank_the_same_words_scattered() -> None:
    registry = FilterRegistry(
        [
            FilterDefinition(id="a.quoted", type="boolean", description="free airport shuttle"),
            FilterDefinition(id="b.scattered", type="boolean", description="shuttle airport free"),
        ]
    )

    candidates = retrieve(registry, "I need a free airport shuttle")

    assert [candidate.definition.id for candidate in candidates] == ["a.quoted", "b.scattered"]
    assert candidates[0].score > candidates[1].score


def test_respects_top_k() -> None:
    candidates = retrieve(FilterRegistry.default(), "parking pool breakfast wifi spa gym", top_k=5)

    assert len(candidates) == 5


def test_returns_nothing_for_unrelated_text() -> None:
    assert retrieve(FilterRegistry.default(), "what is the capital of France") == []


def test_definition_text_excludes_backend_provenance() -> None:
    definition = FilterDefinition(
        id="hotel.parking",
        type="boolean",
        description="Property offers parking",
        aliases=["car park"],
        source={"facility_id": 2, "facility_name": "PARKING"},
    )

    text = definition_to_text(definition)

    assert "car park" in text
    assert "facility_id" not in text
    assert "PARKING" not in text
