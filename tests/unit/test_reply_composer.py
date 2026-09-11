from datetime import date

from hotel_assistance.application.reply_composer import (
    compose_filters_reply,
    compose_offers_reply,
    compose_out_of_scope_reply,
    compose_simulated_search_reply,
    join_replies,
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
        FilterDefinition(id="hotel.parking", type="boolean", description="Parking", aliases=["parking"]),
        FilterDefinition(
            id="room.size_m2", type="range", description="Room floor area", aliases=["room size"], unit="m2"
        ),
        FilterDefinition(id="hotel.pool", type="boolean", description="Property offers a swimming pool"),
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


def compose_parts(**overrides) -> tuple[str, str]:
    """Both halves of a turn, composed the way the orchestrator composes them."""

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
    arguments = {**defaults, **overrides}
    filters = compose_filters_reply(
        state=arguments["state"],
        registry=arguments["registry"],
        applied=arguments["applied"],
        applied_trip=arguments["applied_trip"],
        issues=arguments["issues"],
        unmapped_requests=arguments["unmapped_requests"],
        clarification_question=arguments["clarification_question"],
        was_reset=arguments["was_reset"],
        destination_hint=arguments["destination_hint"],
        date_hint=arguments["date_hint"],
    )
    offers = compose_offers_reply(
        state=arguments["state"],
        registry=arguments["registry"],
        available_offers_count=arguments["available_offers_count"],
        relaxations=arguments["relaxations"],
        include_trip=not filters.named_trip,
    )
    return filters.text, offers


def compose(**overrides) -> str:
    return join_replies(*compose_parts(**overrides))


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
    assert "hotels available" not in compose(state=haarlem_state())
    assert "There are 7 hotels available" in compose(state=haarlem_state(), available_offers_count=7)


def test_the_offer_count_is_stated_against_the_search_it_answers() -> None:
    reply = compose(state=haarlem_state(), available_offers_count=38)

    assert "There are 38 hotels available in Haarlem for 15-18 Aug 2026 that match your filters." in reply


def test_the_trip_is_named_once_per_reply() -> None:
    reply = compose(
        state=haarlem_state(),
        applied_trip=[TripField.DESTINATION],
        available_offers_count=38,
    )

    # The "Got it" line already said where and when, so the count does not.
    assert reply.startswith("Got it: Haarlem, 15-18 Aug 2026 and 1 adult.")
    assert "There are 38 hotels available that match your filters." in reply
    assert reply.count("Haarlem") == 1


def test_a_single_offer_is_stated_in_the_singular() -> None:
    reply = compose(state=haarlem_state(), available_offers_count=1)

    assert "There is 1 hotel available in Haarlem for 15-18 Aug 2026 that matches your filters." in reply


def test_the_offer_count_claims_no_filters_when_none_are_set() -> None:
    reply = compose(state=haarlem_state(filters=[]), available_offers_count=38)

    assert "There are 38 hotels available in Haarlem for 15-18 Aug 2026." in reply


def test_the_offer_count_states_only_the_trip_details_it_has() -> None:
    reply = compose(state=SearchState(), available_offers_count=38)

    assert "There are 38 hotels available." in reply


def test_a_zero_result_offers_the_preferences_and_promises_the_requirements() -> None:
    reply = compose(
        state=haarlem_state(
            filters=[
                AppliedFilter(filter_id="hotel.parking", value=True),
                AppliedFilter(filter_id="room.size_m2", value=RangeValue(min=30), strength="preferred"),
            ]
        ),
        available_offers_count=0,
    )

    assert "No hotels match all of your current filters." in reply
    assert "removing some preferences, such as room size (at least 30 m2)" in reply
    assert "keeping your required criteria like parking" in reply
    assert reply.endswith("Would you like me to relax those preferences?")


def test_a_zero_result_never_volunteers_to_drop_a_requirement() -> None:
    reply = compose(
        state=haarlem_state(
            filters=[
                AppliedFilter(filter_id="hotel.parking", value=True),
                AppliedFilter(filter_id="room.size_m2", value=RangeValue(min=30), strength="preferred"),
            ]
        ),
        available_offers_count=0,
    )

    offer, _, _ = reply.partition("while keeping")
    assert "parking" not in offer


def test_a_zero_result_with_only_requirements_asks_which_one_to_give_up() -> None:
    reply = compose(
        state=haarlem_state(
            filters=[
                AppliedFilter(filter_id="hotel.parking", value=True),
                AppliedFilter(filter_id="room.size_m2", value=RangeValue(min=30)),
            ]
        ),
        available_offers_count=0,
        # Ranked by the domain service: a numeric limit can be widened rather
        # than dropped, so it is offered first.
        relaxations=[
            RelaxationSuggestion(filter_id="room.size_m2", label="Room floor area", reason="widen it"),
            RelaxationSuggestion(filter_id="hotel.parking", label="Parking", reason="drop it"),
        ],
    )

    assert "Every filter you set is a required one" in reply
    assert "such as room size (at least 30 m2) or parking" in reply
    assert reply.endswith("Which of them would you like me to relax?")


def test_a_zero_result_with_no_filters_points_at_the_trip_details() -> None:
    reply = compose(state=haarlem_state(filters=[]), available_offers_count=0)

    assert "No hotels match this search." in reply
    assert "no filters to relax" in reply
    assert "dates or the destination" in reply


def test_an_excluded_filter_is_named_as_an_exclusion() -> None:
    reply = compose(
        state=haarlem_state(filters=[AppliedFilter(filter_id="hotel.parking", value=False, strength="preferred")]),
        available_offers_count=0,
    )

    assert "such as no parking" in reply


def test_a_filter_without_an_alias_falls_back_to_its_description() -> None:
    reply = compose(
        state=haarlem_state(filters=[AppliedFilter(filter_id="hotel.pool", value=True, strength="preferred")]),
        available_offers_count=0,
    )

    assert "such as Property offers a swimming pool" in reply


def test_only_a_few_filters_are_named_in_a_zero_result() -> None:
    reply = compose(
        state=haarlem_state(
            filters=[
                AppliedFilter(filter_id="hotel.parking", value=True, strength="preferred"),
                AppliedFilter(filter_id="hotel.pool", value=True, strength="preferred"),
                AppliedFilter(filter_id="room.size_m2", value=RangeValue(min=30), strength="preferred"),
            ]
        ),
        available_offers_count=0,
    )

    # Three named is the cap, and they are joined as alternatives, not as a list.
    assert reply.count(" or ") == 1
    assert "such as parking, Property offers a swimming pool or room size (at least 30 m2)" in reply


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


def test_a_turn_that_changes_nothing_says_nothing() -> None:
    """The fallback belongs to the turn, not to either half of it."""

    assert compose(state=haarlem_state()) == ""


def test_the_two_halves_are_composed_separately() -> None:
    """The filter summary is ready before the backend has answered anything."""

    filters, offers = compose_parts(
        state=haarlem_state(),
        applied_trip=[TripField.DESTINATION],
        applied=[FilterOperation(op="add", filter_id="hotel.parking", value=True)],
        available_offers_count=38,
    )

    assert filters == "Got it: Haarlem, 15-18 Aug 2026 and 1 adult. Applied: Parking."
    assert offers == "There are 38 hotels available that match your filters."


def test_the_offers_half_stays_empty_until_the_backend_answers() -> None:
    _, offers = compose_parts(state=haarlem_state(), available_offers_count=None)

    assert offers == ""


def test_the_offers_half_names_the_trip_when_the_filters_half_did_not() -> None:
    filters, offers = compose_parts(state=haarlem_state(), available_offers_count=38)

    assert filters == ""
    assert offers == "There are 38 hotels available in Haarlem for 15-18 Aug 2026 that match your filters."


def test_an_out_of_scope_reply_keeps_the_search_it_refuses_to_change() -> None:
    reply = compose_out_of_scope_reply(haarlem_state())

    assert "hotel-search filters" in reply
    assert "Your current search is unchanged: Haarlem, 15-18 Aug 2026, 1 adult and 1 saved preference." in reply


def test_an_out_of_scope_reply_on_an_empty_search_stays_short() -> None:
    assert "unchanged" not in compose_out_of_scope_reply(SearchState())


def test_a_simulated_search_reports_only_what_the_backend_returned() -> None:
    assert "There are 32 hotels available in Haarlem" in compose_simulated_search_reply(
        haarlem_state(), REGISTRY, 32, []
    )
    assert "There is 1 hotel available in Haarlem" in compose_simulated_search_reply(
        haarlem_state(), REGISTRY, 1, []
    )


def test_a_simulated_search_with_no_offers_offers_relaxations() -> None:
    reply = compose_simulated_search_reply(
        haarlem_state(filters=[AppliedFilter(filter_id="hotel.parking", value=True, strength="preferred")]),
        REGISTRY,
        0,
        [RelaxationSuggestion(filter_id="hotel.parking", label="Parking", reason="a preference")],
    )

    assert "No hotels match all of your current filters." in reply
    assert "such as parking" in reply


def test_a_simulated_search_never_invents_a_count() -> None:
    assert "cannot say how many" in compose_simulated_search_reply(haarlem_state(), REGISTRY, None, [])


def test_a_capped_simulated_count_is_explained() -> None:
    reply = compose_simulated_search_reply(
        haarlem_state(), REGISTRY, 500, [], "The simulator caps a test run at 500 offers."
    )

    assert "There are 500 hotels available" in reply
    assert "caps a test run at 500" in reply
