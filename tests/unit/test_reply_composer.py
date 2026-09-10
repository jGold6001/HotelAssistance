from datetime import date

from hotel_assistance.application.reply_composer import (
    compose_out_of_scope_reply,
    compose_reply,
)
from hotel_assistance.domain.models.applied_filter import AppliedFilter
from hotel_assistance.domain.models.filter_definition import FilterDefinition
from hotel_assistance.domain.models.filter_operation import FilterOperation
from hotel_assistance.domain.models.filter_value import RangeValue
from hotel_assistance.domain.models.guest_config import GuestConfig
from hotel_assistance.domain.models.search_state import SearchState
from hotel_assistance.domain.services.filter_registry import FilterRegistry
from hotel_assistance.domain.services.relaxation import RelaxationSuggestion
from hotel_assistance.domain.services.search_validator import (
    IssueCode,
    TripField,
    ValidationIssue,
)

REGISTRY = FilterRegistry(
    [
        FilterDefinition(id="hotel.parking", type="boolean", description="Parking"),
        FilterDefinition(id="room.size_m2", type="range", description="Room floor area", unit="m2"),
    ]
)


def haarlem_state(**overrides) -> SearchState:
    """The state the example dialogue reaches after its first message."""

    defaults = dict(
        destination="Haarlem",
        check_in=date(2026, 8, 15),
        check_out=date(2026, 8, 18),
        guests=GuestConfig(adults=1),
        filters=[AppliedFilter(filter_id="hotel.parking", value=True)],
    )
    return SearchState(**{**defaults, **overrides})


def compose(**overrides) -> str:
    defaults = dict(
        state=SearchState(),
        registry=REGISTRY,
        applied=[],
        applied_trip=[],
        issues=[],
        unmapped_requests=[],
        clarification_question=None,
        available_offers_count=None,
        relaxations=[],
        was_reset=False,
        destination_hint=None,
        date_hint=None,
    )
    return compose_reply(**{**defaults, **overrides})


def test_applied_operations_are_named() -> None:
    reply = compose(
        state=haarlem_state(),
        applied=[
            FilterOperation(op="add", filter_id="hotel.parking", value=True),
            FilterOperation(op="add", filter_id="room.size_m2", value=RangeValue(min=30)),
        ],
    )

    assert "Applied: Parking and Room floor area (at least 30 m2)." in reply


def test_removals_are_reported_separately() -> None:
    reply = compose(applied=[FilterOperation(op="remove", filter_id="hotel.parking")])

    assert "Removed: Parking." in reply


def test_a_filter_set_to_false_is_described_as_an_exclusion_not_a_removal() -> None:
    reply = compose(applied=[FilterOperation(op="add", filter_id="hotel.parking", value=False)])

    assert "Excluding properties with: Parking." in reply
    assert "Removed" not in reply


def test_conflicts_ask_the_user_to_decide() -> None:
    reply = compose(
        issues=[
            ValidationIssue(
                code=IssueCode.CONFLICT,
                message="'A' conflicts with 'B', which is already active.",
                filter_id="a",
                conflicting_filter_id="b",
            )
        ]
    )

    assert "conflicts with" in reply
    assert "which of the two you want to keep" in reply


def test_offer_count_is_only_stated_when_the_backend_supplied_one() -> None:
    assert "offers" not in compose(state=haarlem_state())
    assert "matches 7 offers" in compose(state=haarlem_state(), available_offers_count=7)


def test_zero_offers_lists_the_relaxation_options() -> None:
    reply = compose(
        state=haarlem_state(),
        available_offers_count=0,
        relaxations=[RelaxationSuggestion(filter_id="hotel.parking", label="Parking", reason="a preference")],
    )

    assert "no offers" in reply
    assert "You could relax: Parking - a preference." in reply


def test_clarification_takes_precedence_over_the_generic_missing_info_prompt() -> None:
    reply = compose(clarification_question="Which city?")

    assert "Which city?" in reply
    assert "where you want to stay" not in reply


def test_missing_trip_details_are_read_from_the_state_not_from_the_model() -> None:
    reply = compose(state=SearchState(destination="Haarlem", guests=GuestConfig(adults=1)))

    assert "your check-in and check-out dates" in reply
    assert "where you want to stay" not in reply
    assert "how many people" not in reply


def test_only_the_open_side_of_a_half_specified_stay_is_requested() -> None:
    reply = compose(state=haarlem_state(check_out=None))

    assert "your check-out date" in reply
    assert "check-in and check-out" not in reply


def test_applied_trip_details_are_confirmed_back() -> None:
    reply = compose(state=haarlem_state(), applied_trip=[TripField.DESTINATION, TripField.DATES])

    assert reply.startswith("Got it: Haarlem, 15-18 Aug 2026 and 1 adult.")


def test_a_follow_up_question_says_what_the_search_still_holds() -> None:
    """The point of the "in May" turn: nothing else has to be repeated."""

    reply = compose(
        state=haarlem_state(check_in=None, check_out=None),
        applied_trip=[TripField.DATES],
        clarification_question="What dates in May, and which year?",
        date_hint="May",
    )

    assert reply == (
        "I still have Haarlem, 1 adult and 1 saved preference. "
        "What dates in May, and which year?"
    )


def test_the_fallback_question_echoes_the_users_own_words() -> None:
    reply = compose(
        state=haarlem_state(check_in=None, check_out=None),
        applied_trip=[TripField.DATES],
        date_hint="May",
    )

    assert 'your check-in and check-out dates (you said "May")' in reply


def test_a_long_list_of_unmapped_requests_does_not_bury_the_reply() -> None:
    reply = compose(
        state=haarlem_state(),
        unmapped_requests=["a rain shower", "a real double bed", "reading lights", "Dutch-speaking staff"],
    )

    assert "a rain shower; a real double bed; reading lights, and 1 more." in reply
    assert "Dutch-speaking staff" not in reply


def test_a_turn_that_changes_nothing_asks_for_more_detail() -> None:
    assert "Could you say a bit more" in compose(state=haarlem_state())


def test_an_out_of_scope_reply_keeps_the_search_it_refuses_to_change() -> None:
    reply = compose_out_of_scope_reply(haarlem_state())

    assert "hotel-search filters" in reply
    assert "Your current search is unchanged: Haarlem, 15-18 Aug 2026, 1 adult and 1 saved preference." in reply


def test_an_out_of_scope_reply_on_an_empty_search_stays_short() -> None:
    assert "unchanged" not in compose_out_of_scope_reply(SearchState())
