import asyncio

import pytest
from hotel_assistance.application.chat_orchestrator import ChatOrchestrator, ChatStage
from hotel_assistance.application.session_store import SessionStore
from hotel_assistance.domain.models.candidate_filter import CandidateFilter
from hotel_assistance.domain.models.extraction import (
    ExtractedFilter,
    ExtractionResult,
    GuestCounts,
    TripDetails,
)
from hotel_assistance.domain.models.filter_definition import FilterDefinition
from hotel_assistance.domain.models.filter_value import RangeValue
from hotel_assistance.domain.services.filter_registry import FilterRegistry
from hotel_assistance.domain.services.search_validator import IssueCode, SearchValidator
from hotel_assistance.infrastructure.hotel_search.client import (
    HotelSearchError,
    OfferCount,
)
from hotel_assistance.infrastructure.llm.provider import LLMExtractionError

PARKING = FilterDefinition(id="hotel.parking", type="boolean", description="Parking")
QUIET = FilterDefinition(id="room.soundproofing", type="boolean", description="Soundproofed room")
SIZE = FilterDefinition(
    id="room.size_m2", type="range", description="Room floor area", unit="m2", bounds={"min": 0, "max": 500}
)


class FakeRetriever:
    def __init__(self, definitions: list[FilterDefinition]) -> None:
        self._definitions = definitions
        self.queries: list[str] = []

    async def retrieve(self, query: str, top_k: int) -> list[CandidateFilter]:
        self.queries.append(query)
        return [CandidateFilter(definition=item, score=1.0) for item in self._definitions][:top_k]


class FakeLLM:
    def __init__(self, *results: ExtractionResult, error: Exception | None = None) -> None:
        self._results = list(results)
        self._error = error
        self.requests: list = []

    async def extract(self, request):
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        return self._results.pop(0)


class FakeHotelSearch:
    def __init__(self, count: int | None = None, error: Exception | None = None) -> None:
        self._count = count
        self._error = error

    async def count_offers(self, state) -> OfferCount:
        if self._error is not None:
            raise self._error
        return OfferCount(available_offers_count=self._count, backend_available=True)


def build_orchestrator(llm, hotel_search=None, definitions=None) -> ChatOrchestrator:
    registry = FilterRegistry(definitions or [PARKING, QUIET, SIZE])
    return ChatOrchestrator(
        registry=registry,
        retriever=FakeRetriever(registry.list_all()),
        llm_provider=llm,
        validator=SearchValidator(registry),
        hotel_search_client=hotel_search or FakeHotelSearch(),
        sessions=SessionStore(),
        top_k=10,
    )


def extraction(*filters: ExtractedFilter, **kwargs) -> ExtractionResult:
    return ExtractionResult(filters=list(filters), **kwargs)


def test_filters_from_a_message_reach_the_state() -> None:
    orchestrator = build_orchestrator(
        FakeLLM(
            extraction(
                ExtractedFilter(
                    filter_id="hotel.parking", op="add", type="boolean", strength="required", boolean_value=True
                ),
                ExtractedFilter(
                    filter_id="room.size_m2",
                    op="add",
                    type="range",
                    strength="required",
                    range_value=RangeValue(min=30),
                ),
                trip=TripDetails(destination="Haarlem", guests=GuestCounts(adults=1)),
            )
        )
    )

    result = asyncio.run(orchestrator.handle_message("s1", "Parking and a room of at least 30 m2 in Haarlem"))

    assert result.state.destination == "Haarlem"
    assert result.state.filter_by_id("hotel.parking").value is True
    assert result.state.filter_by_id("room.size_m2").value == RangeValue(min=30)
    assert "Parking" in result.reply


def test_state_persists_across_turns_in_a_session() -> None:
    orchestrator = build_orchestrator(
        FakeLLM(
            extraction(
                ExtractedFilter(
                    filter_id="hotel.parking", op="add", type="boolean", strength="required", boolean_value=True
                )
            ),
            extraction(
                ExtractedFilter(
                    filter_id="room.soundproofing",
                    op="add",
                    type="boolean",
                    strength="preferred",
                    boolean_value=True,
                )
            ),
        )
    )

    asyncio.run(orchestrator.handle_message("s1", "I need parking"))
    result = asyncio.run(orchestrator.handle_message("s1", "a quiet room would be nice too"))

    assert {item.filter_id for item in result.state.filters} == {"hotel.parking", "room.soundproofing"}


def test_sessions_are_isolated() -> None:
    orchestrator = build_orchestrator(
        FakeLLM(
            extraction(
                ExtractedFilter(
                    filter_id="hotel.parking", op="add", type="boolean", strength="required", boolean_value=True
                )
            ),
            extraction(),
        )
    )

    asyncio.run(orchestrator.handle_message("s1", "I need parking"))
    other = asyncio.run(orchestrator.handle_message("s2", "hello"))

    assert other.state.filters == []
    assert orchestrator.state_for("s1").filters != []


def test_hallucinated_filter_ids_never_reach_the_state() -> None:
    orchestrator = build_orchestrator(
        FakeLLM(
            extraction(
                ExtractedFilter(
                    filter_id="hotel.helipad", op="add", type="boolean", strength="required", boolean_value=True
                )
            )
        )
    )

    result = asyncio.run(orchestrator.handle_message("s1", "I want a helipad"))

    assert result.state.filters == []
    assert [issue.code for issue in result.issues] == [IssueCode.UNKNOWN_FILTER]


def test_unrelated_requests_are_refused_without_touching_the_state() -> None:
    orchestrator = build_orchestrator(FakeLLM(extraction(is_hotel_search_related=False)))

    result = asyncio.run(orchestrator.handle_message("s1", "write me a poem about otters"))

    assert result.state.filters == []
    assert "hotel-search filters" in result.reply


def test_clarification_question_is_passed_through() -> None:
    orchestrator = build_orchestrator(
        FakeLLM(extraction(clarification_question="Which city did you have in mind?"))
    )

    result = asyncio.run(orchestrator.handle_message("s1", "somewhere sunny"))

    assert "Which city did you have in mind?" in result.reply


def test_missing_trip_info_is_requested_when_no_question_was_asked() -> None:
    orchestrator = build_orchestrator(FakeLLM(extraction(missing_trip_info=["destination", "dates"])))

    result = asyncio.run(orchestrator.handle_message("s1", "two adults"))

    assert "where you want to stay" in result.reply
    assert "check-in and check-out dates" in result.reply


def test_unmapped_requests_are_reported_rather_than_silently_dropped() -> None:
    orchestrator = build_orchestrator(FakeLLM(extraction(unmapped_requests=["a rain shower"])))

    result = asyncio.run(orchestrator.handle_message("s1", "I would love a rain shower"))

    assert "a rain shower" in result.reply
    assert result.unmapped_requests == ["a rain shower"]


def test_zero_results_produce_relaxation_suggestions_from_the_current_state() -> None:
    orchestrator = build_orchestrator(
        FakeLLM(
            extraction(
                ExtractedFilter(
                    filter_id="room.soundproofing",
                    op="add",
                    type="boolean",
                    strength="preferred",
                    boolean_value=True,
                ),
                ExtractedFilter(
                    filter_id="room.size_m2",
                    op="add",
                    type="range",
                    strength="required",
                    range_value=RangeValue(min=200),
                ),
                trip=TripDetails(
                    destination="Haarlem",
                    check_in="2026-08-15",
                    check_out="2026-08-18",
                    guests=GuestCounts(adults=1),
                ),
            )
        ),
        hotel_search=FakeHotelSearch(count=0),
    )

    result = asyncio.run(orchestrator.handle_message("s1", "huge quiet room in Haarlem 15-18 Aug, solo"))

    assert result.available_offers_count == 0
    assert [item.filter_id for item in result.relaxation_suggestions] == ["room.soundproofing", "room.size_m2"]
    assert "no offers" in result.reply


def test_offer_count_is_unknown_until_the_search_is_complete() -> None:
    orchestrator = build_orchestrator(FakeLLM(extraction()), hotel_search=FakeHotelSearch(count=17))

    result = asyncio.run(orchestrator.handle_message("s1", "hello"))

    assert result.available_offers_count is None
    assert result.backend_available is False


def test_backend_failure_never_fabricates_a_count() -> None:
    orchestrator = build_orchestrator(
        FakeLLM(
            extraction(
                trip=TripDetails(
                    destination="Haarlem",
                    check_in="2026-08-15",
                    check_out="2026-08-18",
                    guests=GuestCounts(adults=2),
                )
            )
        ),
        hotel_search=FakeHotelSearch(error=HotelSearchError("backend down")),
    )

    result = asyncio.run(orchestrator.handle_message("s1", "Haarlem 15-18 Aug for two"))

    assert result.available_offers_count is None
    assert result.state.destination == "Haarlem"


def test_provider_failure_surfaces_as_an_extraction_error() -> None:
    orchestrator = build_orchestrator(FakeLLM(error=LLMExtractionError("model unavailable")))

    with pytest.raises(LLMExtractionError):
        asyncio.run(orchestrator.handle_message("s1", "I need parking"))


def test_stages_are_reported_in_order() -> None:
    orchestrator = build_orchestrator(FakeLLM(extraction()))
    seen: list[ChatStage] = []

    async def on_stage(stage: ChatStage) -> None:
        seen.append(stage)

    asyncio.run(orchestrator.handle_message("s1", "hello", on_stage=on_stage))

    assert seen == [
        ChatStage.RETRIEVING,
        ChatStage.EXTRACTING,
        ChatStage.VALIDATING,
        ChatStage.SEARCHING,
        ChatStage.DONE,
    ]


def test_conversation_history_is_given_to_the_provider() -> None:
    llm = FakeLLM(extraction(), extraction())
    orchestrator = build_orchestrator(llm)

    first = asyncio.run(orchestrator.handle_message("s1", "first message"))
    asyncio.run(orchestrator.handle_message("s1", "second message"))

    history = llm.requests[1].history
    assert [turn.role.value for turn in history] == ["user", "assistant"]
    assert history[0].content == "first message"
    assert history[1].content == first.reply
    # The message being handled is passed separately, not pre-added to history.
    assert llm.requests[1].message == "second message"


def test_reset_clears_the_session() -> None:
    orchestrator = build_orchestrator(
        FakeLLM(
            extraction(
                ExtractedFilter(
                    filter_id="hotel.parking", op="add", type="boolean", strength="required", boolean_value=True
                )
            )
        )
    )

    asyncio.run(orchestrator.handle_message("s1", "I need parking"))
    state = orchestrator.reset("s1")

    assert state.filters == []
