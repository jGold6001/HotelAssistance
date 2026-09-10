import asyncio
from datetime import date

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
from hotel_assistance.domain.models.hotel_offer import HotelOffer
from hotel_assistance.domain.models.trip_field import TripField
from hotel_assistance.domain.services.filter_registry import FilterRegistry
from hotel_assistance.domain.services.search_validator import IssueCode, SearchValidator
from hotel_assistance.infrastructure.hotel_search.client import (
    HotelSearchError,
    OfferResult,
)
from hotel_assistance.infrastructure.hotel_search.simulator import (
    SimulatedHotelSearchClient,
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
        self.requested_counts: list[int | None] = []

    async def search_offers(self, state, requested_count: int | None = None) -> OfferResult:
        self.requested_counts.append(requested_count)
        if self._error is not None:
            raise self._error
        count = self._count if requested_count is None else requested_count
        offers = [
            HotelOffer(apartment=f"Mock {index}", address=f"{index} Test Street", price="$100-$200")
            for index in range(count or 0)
        ]
        return OfferResult(available_offers_count=count, backend_available=True, offers=offers)


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


def test_a_refusal_does_not_cost_the_user_the_search_they_built() -> None:
    orchestrator = build_orchestrator(
        FakeLLM(
            extraction(
                ExtractedFilter(
                    filter_id="hotel.parking", op="add", type="boolean", strength="required", boolean_value=True
                ),
                trip=TripDetails(destination="Haarlem", guests=GuestCounts(adults=1)),
            ),
            extraction(is_hotel_search_related=False),
        )
    )

    asyncio.run(orchestrator.handle_message("s1", "parking in Haarlem for one"))
    result = asyncio.run(orchestrator.handle_message("s1", "write me a poem about otters"))

    assert result.state.destination == "Haarlem"
    assert result.state.filter_by_id("hotel.parking").value is True
    assert "Your current search is unchanged: Haarlem, 1 adult and 1 saved preference." in result.reply


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
    assert "No hotels match all of your current filters." in result.reply
    assert "removing some preferences, such as Soundproofed room" in result.reply


def test_a_bare_test_directive_simulates_a_search_without_the_model() -> None:
    llm = FakeLLM()
    hotel_search = FakeHotelSearch()
    orchestrator = build_orchestrator(llm, hotel_search=hotel_search)

    result = asyncio.run(orchestrator.handle_message("s1", "@test_aparts = 32"))

    assert llm.requests == []
    assert hotel_search.requested_counts == [32]
    assert result.available_offers_count == 32
    assert len(result.offers) == 32
    assert "There are 32 hotels available." in result.reply


def test_a_message_with_no_directive_still_reaches_the_model() -> None:
    llm = FakeLLM(extraction())
    orchestrator = build_orchestrator(llm)

    asyncio.run(orchestrator.handle_message("s1", " "))

    assert len(llm.requests) == 1


def test_a_test_directive_inside_a_request_is_stripped_before_extraction() -> None:
    llm = FakeLLM(
        extraction(
            ExtractedFilter(
                filter_id="hotel.parking", op="add", type="boolean", strength="required", boolean_value=True
            )
        )
    )
    hotel_search = FakeHotelSearch()
    orchestrator = build_orchestrator(llm, hotel_search=hotel_search)

    result = asyncio.run(orchestrator.handle_message("s1", "I need parking @test_aparts = 4"))

    assert llm.requests[0].message == "I need parking"
    assert hotel_search.requested_counts == [4]
    assert result.available_offers_count == 4
    assert len(result.offers) == 4


def test_a_test_directive_leaves_the_search_state_alone() -> None:
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

    result = asyncio.run(orchestrator.handle_message("s1", "@test_aparts = 2"))

    assert [item.filter_id for item in result.state.filters] == ["hotel.parking"]
    assert len(result.offers) == 2


def test_a_zero_directive_still_suggests_relaxations() -> None:
    orchestrator = build_orchestrator(
        FakeLLM(
            extraction(
                ExtractedFilter(
                    filter_id="room.soundproofing",
                    op="add",
                    type="boolean",
                    strength="preferred",
                    boolean_value=True,
                )
            )
        )
    )
    asyncio.run(orchestrator.handle_message("s1", "quiet room"))

    result = asyncio.run(orchestrator.handle_message("s1", "@test_aparts = 0"))

    assert result.available_offers_count == 0
    assert result.offers == []
    assert [item.filter_id for item in result.relaxation_suggestions] == ["room.soundproofing"]
    assert "No hotels match all of your current filters." in result.reply
    assert result.reply.endswith("Would you like me to relax those preferences?")


def test_a_message_without_a_directive_runs_no_simulated_search() -> None:
    """A complete search still gets no offers unless a directive asks for them."""

    orchestrator = build_orchestrator(
        FakeLLM(
            extraction(
                ExtractedFilter(
                    filter_id="hotel.parking", op="add", type="boolean", strength="required", boolean_value=True
                ),
                trip=TripDetails(
                    destination="Haarlem",
                    check_in="2026-08-15",
                    check_out="2026-08-18",
                    guests=GuestCounts(adults=2),
                ),
            )
        ),
        hotel_search=SimulatedHotelSearchClient(),
    )

    result = asyncio.run(orchestrator.handle_message("s1", "parking in Haarlem 15-18 Aug for two"))

    assert result.state.is_ready_for_search()
    assert result.available_offers_count is None
    assert result.backend_available is False
    assert result.offers == []
    assert result.relaxation_suggestions == []
    assert "hotels" not in result.reply


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


def test_the_filter_summary_is_delivered_before_the_search_starts() -> None:
    """Half a reply early beats a whole one after the backend round trip."""

    orchestrator = build_orchestrator(
        FakeLLM(
            extraction(
                ExtractedFilter(
                    filter_id="hotel.parking", op="add", type="boolean", strength="required", boolean_value=True
                ),
                trip=TripDetails(
                    destination="Haarlem",
                    check_in="2026-08-15",
                    check_out="2026-08-18",
                    guests=GuestCounts(adults=1),
                ),
            )
        ),
        hotel_search=FakeHotelSearch(count=7),
    )
    events: list[str] = []

    async def on_stage(stage: ChatStage) -> None:
        events.append(f"stage:{stage.value}")

    async def on_partial(partial) -> None:
        events.append(f"partial:{partial.reply}")
        # Nothing has been asked of the hotel backend yet, so the partial must
        # not carry a count that would then be restated.
        assert partial.available_offers_count is None

    result = asyncio.run(
        orchestrator.handle_message("s1", "parking in Haarlem", on_stage=on_stage, on_partial=on_partial)
    )

    partial_index = next(index for index, event in enumerate(events) if event.startswith("partial:"))
    assert partial_index < events.index(f"stage:{ChatStage.SEARCHING.value}")
    assert events[partial_index] == f"partial:{result.filters_reply}"
    assert "Applied: Parking." in result.filters_reply
    assert result.offers_reply == "There are 7 hotels available that match your filters."
    assert result.reply == f"{result.filters_reply} {result.offers_reply}"


def test_a_turn_with_nothing_to_report_still_answers() -> None:
    """A complete search, an unchanged turn and a silent backend: neither half
    has anything of its own to say, so the fallback carries the turn."""

    orchestrator = build_orchestrator(
        FakeLLM(
            extraction(
                trip=TripDetails(
                    destination="Haarlem",
                    check_in="2026-08-15",
                    check_out="2026-08-18",
                    guests=GuestCounts(adults=1),
                )
            ),
            extraction(),
        ),
        hotel_search=FakeHotelSearch(error=HotelSearchError("backend down")),
    )
    asyncio.run(orchestrator.handle_message("s1", "Haarlem, 15-18 August 2026, one adult"))
    partials: list[str] = []

    async def on_partial(partial) -> None:
        partials.append(partial.reply)

    result = asyncio.run(orchestrator.handle_message("s1", "thanks", on_partial=on_partial))

    assert partials == []
    assert "Could you say a bit more" in result.offers_reply
    assert result.reply == result.offers_reply


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


def haarlem_turn() -> ExtractionResult:
    """The first message of the example dialogue, as the model reads it."""

    return extraction(
        ExtractedFilter(
            filter_id="room.soundproofing", op="add", type="boolean", strength="required", boolean_value=True
        ),
        ExtractedFilter(
            filter_id="room.size_m2", op="add", type="range", strength="required", range_value=RangeValue(min=30)
        ),
        trip=TripDetails(
            destination="Haarlem",
            check_in="2026-08-15",
            check_out="2026-08-18",
            guests=GuestCounts(adults=1),
        ),
        unmapped_requests=["a rain shower"],
    )


def test_the_first_turn_confirms_the_trip_it_understood() -> None:
    orchestrator = build_orchestrator(FakeLLM(haarlem_turn()))

    result = asyncio.run(orchestrator.handle_message("s1", "Haarlem 15-18 Aug, solo, quiet room over 30 m2"))

    assert result.reply.startswith("Got it: Haarlem, 15-18 Aug 2026 and 1 adult.")
    assert "Applied: Soundproofed room and Room floor area (at least 30 m2)." in result.reply
    assert "a rain shower" in result.reply


def test_a_vague_date_change_keeps_the_rest_of_the_search_and_asks() -> None:
    """The reported bug: "I need something in May" after a complete first turn."""

    orchestrator = build_orchestrator(
        FakeLLM(
            haarlem_turn(),
            extraction(
                trip=TripDetails(date_hint="May"),
                clarification_question="What dates in May, and which year?",
                unmapped_requests=["something in May"],
            ),
        )
    )

    asyncio.run(orchestrator.handle_message("s1", "Haarlem 15-18 Aug, solo, quiet room over 30 m2"))
    result = asyncio.run(orchestrator.handle_message("s1", "I need something in May"))

    # The superseded August stay is gone, everything else survives untouched.
    assert result.state.check_in is None and result.state.check_out is None
    assert result.state.destination == "Haarlem"
    assert result.state.guests.adults == 1
    assert {item.filter_id for item in result.state.filters} == {"room.soundproofing", "room.size_m2"}

    assert result.unmapped_requests == []
    assert result.missing_trip_info == ["dates"]
    assert result.reply == (
        "I still have Haarlem, 1 adult and 2 saved preferences. "
        "What dates in May, and which year?"
    )


def test_a_vague_destination_change_drops_the_old_one_and_asks() -> None:
    orchestrator = build_orchestrator(
        FakeLLM(
            haarlem_turn(),
            extraction(
                trip=TripDetails(destination_hint="worldwide"),
                clarification_question=(
                    'Which country or region should I focus on, and by "best deals" '
                    "do you mean lowest price or best value?"
                ),
            ),
        )
    )

    asyncio.run(orchestrator.handle_message("s1", "Haarlem 15-18 Aug, solo, quiet room over 30 m2"))
    result = asyncio.run(orchestrator.handle_message("s1", "Suggest best deals worldwide"))

    assert result.state.destination is None
    assert result.state.check_in == date(2026, 8, 15)
    assert "I still have 15-18 Aug 2026, 1 adult and 2 saved preferences." in result.reply
    assert "Which country or region should I focus on" in result.reply


def test_a_vague_date_change_asks_even_when_the_model_forgets_to() -> None:
    orchestrator = build_orchestrator(
        FakeLLM(haarlem_turn(), extraction(trip=TripDetails(date_hint="sometime in May")))
    )

    asyncio.run(orchestrator.handle_message("s1", "Haarlem 15-18 Aug, solo, quiet room over 30 m2"))
    result = asyncio.run(orchestrator.handle_message("s1", "I need something in May"))

    assert 'your check-in and check-out dates (you said "sometime in May")' in result.reply


def test_a_cleared_search_is_never_counted_against_stale_dates() -> None:
    orchestrator = build_orchestrator(
        FakeLLM(haarlem_turn(), extraction(trip=TripDetails(date_hint="May"))),
        hotel_search=FakeHotelSearch(count=12),
    )

    asyncio.run(orchestrator.handle_message("s1", "Haarlem 15-18 Aug, solo, quiet room over 30 m2"))
    result = asyncio.run(orchestrator.handle_message("s1", "I need something in May"))

    assert result.available_offers_count is None
    assert "offers" not in result.reply


def test_a_superseded_stay_is_remembered_while_the_question_is_open() -> None:
    orchestrator = build_orchestrator(
        FakeLLM(haarlem_turn(), extraction(trip=TripDetails(date_hint="May")), extraction())
    )

    asyncio.run(orchestrator.handle_message("s1", "Haarlem 15-18 Aug, solo, quiet room over 30 m2"))
    asyncio.run(orchestrator.handle_message("s1", "I need something in May"))
    pending = orchestrator._sessions.get("s1").pending

    assert pending.field is TripField.DATES
    assert (pending.previous_check_in, pending.previous_check_out) == (date(2026, 8, 15), date(2026, 8, 18))

    # It outlives a turn that is about something else entirely.
    asyncio.run(orchestrator.handle_message("s1", "does it matter if there is parking?"))
    assert orchestrator._sessions.get("s1").pending is not None


def test_the_superseded_stay_can_be_restored_from_what_was_remembered() -> None:
    """"Never mind, keep August" - the model reads PENDING_CHANGE, not the transcript."""

    orchestrator = build_orchestrator(
        FakeLLM(
            haarlem_turn(),
            extraction(trip=TripDetails(date_hint="May")),
            extraction(trip=TripDetails(check_in="2026-08-15", check_out="2026-08-18")),
        )
    )

    asyncio.run(orchestrator.handle_message("s1", "Haarlem 15-18 Aug, solo, quiet room over 30 m2"))
    asyncio.run(orchestrator.handle_message("s1", "I need something in May"))

    result = asyncio.run(orchestrator.handle_message("s1", "actually, keep August"))

    # The remembered value is what the model was given to answer from.
    restore_request = orchestrator._llm_provider.requests[-1]
    assert restore_request.pending.hint == "May"
    assert restore_request.pending.previous_check_in == date(2026, 8, 15)

    assert (result.state.check_in, result.state.check_out) == (date(2026, 8, 15), date(2026, 8, 18))
    assert orchestrator._sessions.get("s1").pending is None
    assert result.reply.startswith("Got it: Haarlem, 15-18 Aug 2026 and 1 adult.")


def test_an_answered_question_stops_being_remembered() -> None:
    orchestrator = build_orchestrator(
        FakeLLM(
            haarlem_turn(),
            extraction(trip=TripDetails(date_hint="May")),
            extraction(trip=TripDetails(check_in="2027-05-12", check_out="2027-05-15")),
        )
    )

    asyncio.run(orchestrator.handle_message("s1", "Haarlem 15-18 Aug, solo, quiet room over 30 m2"))
    asyncio.run(orchestrator.handle_message("s1", "I need something in May"))
    result = asyncio.run(orchestrator.handle_message("s1", "the 12th to the 15th, 2027"))

    assert result.state.check_in == date(2027, 5, 12)
    assert orchestrator._sessions.get("s1").pending is None


def test_starting_over_forgets_the_open_question() -> None:
    orchestrator = build_orchestrator(
        FakeLLM(
            haarlem_turn(),
            extraction(trip=TripDetails(date_hint="May")),
            extraction(reset_requested=True),
        )
    )

    asyncio.run(orchestrator.handle_message("s1", "Haarlem 15-18 Aug, solo, quiet room over 30 m2"))
    asyncio.run(orchestrator.handle_message("s1", "I need something in May"))
    asyncio.run(orchestrator.handle_message("s1", "let us start over"))

    assert orchestrator._sessions.get("s1").pending is None


def test_the_open_question_keeps_echoing_the_users_own_words() -> None:
    orchestrator = build_orchestrator(
        FakeLLM(haarlem_turn(), extraction(trip=TripDetails(date_hint="May")), extraction())
    )

    asyncio.run(orchestrator.handle_message("s1", "Haarlem 15-18 Aug, solo, quiet room over 30 m2"))
    asyncio.run(orchestrator.handle_message("s1", "I need something in May"))
    result = asyncio.run(orchestrator.handle_message("s1", "anything else you need?"))

    assert 'your check-in and check-out dates (you said "May")' in result.reply
