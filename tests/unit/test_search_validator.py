from datetime import date

from hotel_assistance.domain.models.applied_filter import AppliedFilter
from hotel_assistance.domain.models.filter_definition import FilterDefinition
from hotel_assistance.domain.models.filter_operation import FilterOperation
from hotel_assistance.domain.models.filter_value import RangeValue
from hotel_assistance.domain.models.guest_config import GuestConfig
from hotel_assistance.domain.models.search_patch import SearchPatch
from hotel_assistance.domain.models.search_state import SearchState
from hotel_assistance.domain.models.strength import FilterStrength
from hotel_assistance.domain.services.filter_registry import FilterRegistry
from hotel_assistance.domain.services.search_validator import (
    IssueCode,
    SearchValidator,
    TripField,
)


def build_registry() -> FilterRegistry:
    return FilterRegistry(
        [
            FilterDefinition(id="hotel.parking", type="boolean", description="Parking"),
            FilterDefinition(
                id="hotel.non_smoking_rooms",
                type="boolean",
                description="Non-smoking rooms",
                conflicts_with=["hotel.designated_smoking_area"],
            ),
            FilterDefinition(
                id="hotel.designated_smoking_area", type="boolean", description="Smoking area"
            ),
            FilterDefinition(
                id="rating.stars",
                type="range",
                description="Star rating",
                unit="stars",
                bounds={"min": 1, "max": 5},
            ),
        ]
    )


def build_validator() -> SearchValidator:
    return SearchValidator(build_registry())


def test_add_operation_applies_filter() -> None:
    result = build_validator().apply(
        SearchState(),
        SearchPatch(operations=[FilterOperation(op="add", filter_id="hotel.parking", value=True)]),
    )

    assert result.issues == []
    assert result.state.filter_by_id("hotel.parking").value is True


def test_unchanged_state_is_preserved() -> None:
    state = SearchState(
        destination="Haarlem",
        guests=GuestConfig(adults=2),
        filters=[AppliedFilter(filter_id="hotel.parking", value=True)],
    )

    result = build_validator().apply(
        state,
        SearchPatch(operations=[FilterOperation(op="add", filter_id="rating.stars", value=RangeValue(min=4))]),
    )

    assert result.state.destination == "Haarlem"
    assert result.state.guests.adults == 2
    assert result.state.filter_by_id("hotel.parking") is not None
    assert result.state.filter_by_id("rating.stars").value == RangeValue(min=4)


def test_update_replaces_an_existing_value() -> None:
    state = SearchState(filters=[AppliedFilter(filter_id="rating.stars", value=RangeValue(min=3))])

    result = build_validator().apply(
        state,
        SearchPatch(operations=[FilterOperation(op="update", filter_id="rating.stars", value=RangeValue(min=5))]),
    )

    assert len(result.state.filters) == 1
    assert result.state.filter_by_id("rating.stars").value == RangeValue(min=5)


def test_remove_drops_an_applied_filter() -> None:
    state = SearchState(filters=[AppliedFilter(filter_id="hotel.parking", value=True)])

    result = build_validator().apply(
        state, SearchPatch(operations=[FilterOperation(op="remove", filter_id="hotel.parking")])
    )

    assert result.state.filters == []


def test_remove_of_unset_filter_is_reported_not_fatal() -> None:
    result = build_validator().apply(
        SearchState(), SearchPatch(operations=[FilterOperation(op="remove", filter_id="hotel.parking")])
    )

    assert [issue.code for issue in result.issues] == [IssueCode.NOT_APPLIED]
    assert result.state.filters == []


def test_unknown_filter_is_rejected() -> None:
    result = build_validator().apply(
        SearchState(), SearchPatch(operations=[FilterOperation(op="add", filter_id="hotel.unicorn", value=True)])
    )

    assert [issue.code for issue in result.issues] == [IssueCode.UNKNOWN_FILTER]
    assert result.state.filters == []


def test_out_of_bounds_range_is_rejected() -> None:
    result = build_validator().apply(
        SearchState(),
        SearchPatch(operations=[FilterOperation(op="add", filter_id="rating.stars", value=RangeValue(min=9))]),
    )

    assert [issue.code for issue in result.issues] == [IssueCode.INVALID_VALUE]
    assert result.state.filters == []


def test_conflicting_filter_is_rejected_and_reported() -> None:
    state = SearchState(filters=[AppliedFilter(filter_id="hotel.non_smoking_rooms", value=True)])

    result = build_validator().apply(
        state,
        SearchPatch(
            operations=[FilterOperation(op="add", filter_id="hotel.designated_smoking_area", value=True)]
        ),
    )

    assert [issue.code for issue in result.issues] == [IssueCode.CONFLICT]
    assert result.conflicts[0].conflicting_filter_id == "hotel.non_smoking_rooms"
    # The existing filter survives: the app never silently picks a winner.
    assert result.state.filter_by_id("hotel.non_smoking_rooms").value is True
    assert result.state.filter_by_id("hotel.designated_smoking_area") is None


def test_removal_in_the_same_patch_clears_the_way_for_the_conflicting_filter() -> None:
    state = SearchState(filters=[AppliedFilter(filter_id="hotel.non_smoking_rooms", value=True)])

    result = build_validator().apply(
        state,
        SearchPatch(
            operations=[
                FilterOperation(op="add", filter_id="hotel.designated_smoking_area", value=True),
                FilterOperation(op="remove", filter_id="hotel.non_smoking_rooms"),
            ]
        ),
    )

    assert result.issues == []
    assert result.state.filter_by_id("hotel.designated_smoking_area").value is True
    assert result.state.filter_by_id("hotel.non_smoking_rooms") is None


def test_negative_request_does_not_conflict() -> None:
    state = SearchState(filters=[AppliedFilter(filter_id="hotel.non_smoking_rooms", value=True)])

    result = build_validator().apply(
        state,
        SearchPatch(
            operations=[FilterOperation(op="add", filter_id="hotel.designated_smoking_area", value=False)]
        ),
    )

    assert result.issues == []
    assert result.state.filter_by_id("hotel.designated_smoking_area").value is False


def test_self_contradicting_operations_on_one_filter_are_rejected() -> None:
    result = build_validator().apply(
        SearchState(),
        SearchPatch(
            operations=[
                FilterOperation(op="add", filter_id="hotel.parking", value=True),
                FilterOperation(op="add", filter_id="hotel.parking", value=False),
            ]
        ),
    )

    assert [issue.code for issue in result.issues] == [IssueCode.CONFLICT]
    assert result.issues[0].filter_id == "hotel.parking"
    assert result.state.filter_by_id("hotel.parking") is None


def test_repeated_operations_with_the_same_value_are_not_a_conflict() -> None:
    result = build_validator().apply(
        SearchState(),
        SearchPatch(
            operations=[
                FilterOperation(op="add", filter_id="hotel.parking", value=True),
                FilterOperation(op="add", filter_id="hotel.parking", value=True),
            ]
        ),
    )

    assert result.issues == []
    assert result.state.filter_by_id("hotel.parking").value is True


def test_a_superseded_stay_is_cleared_when_no_new_dates_are_known() -> None:
    """"I need something in May" must not leave the August stay in the search."""

    result = build_validator().apply(
        SearchState(check_in=date(2026, 8, 15), check_out=date(2026, 8, 18), destination="Haarlem"),
        SearchPatch(clear_dates=True),
    )

    assert result.state.check_in is None
    assert result.state.check_out is None
    assert result.state.destination == "Haarlem"
    assert result.applied_trip == [TripField.DATES]


def test_clearing_the_dates_does_not_pair_a_new_date_with_the_old_one() -> None:
    result = build_validator().apply(
        SearchState(check_in=date(2026, 8, 15), check_out=date(2026, 8, 18)),
        SearchPatch(check_in=date(2027, 5, 12), clear_dates=True),
    )

    assert result.state.check_in == date(2027, 5, 12)
    assert result.state.check_out is None
    assert result.issues == []


def test_a_named_destination_wins_over_the_request_to_clear_it() -> None:
    result = build_validator().apply(
        SearchState(destination="Haarlem"),
        SearchPatch(destination="Utrecht", clear_destination=True),
    )

    assert result.state.destination == "Utrecht"
    assert result.applied_trip == [TripField.DESTINATION]


def test_clearing_what_is_not_set_changes_nothing() -> None:
    result = build_validator().apply(SearchState(), SearchPatch(clear_dates=True, clear_destination=True))

    assert result.applied_trip == []


def test_applied_trip_fields_report_only_what_changed() -> None:
    result = build_validator().apply(
        SearchState(),
        SearchPatch(destination="Haarlem", guests=GuestConfig(adults=2)),
    )

    assert result.applied_trip == [TripField.DESTINATION, TripField.GUESTS]


def test_rejected_dates_are_not_reported_as_applied() -> None:
    result = build_validator().apply(
        SearchState(),
        SearchPatch(check_in=date(2026, 8, 18), check_out=date(2026, 8, 15)),
    )

    assert result.applied_trip == []
    assert [issue.code for issue in result.issues] == [IssueCode.INVALID_DATES]


def test_dates_are_applied_when_the_range_is_valid() -> None:
    result = build_validator().apply(
        SearchState(), SearchPatch(check_in=date(2026, 8, 15), check_out=date(2026, 8, 18))
    )

    assert result.state.date_range().check_out == date(2026, 8, 18)


def test_inverted_dates_are_rejected_and_state_is_unchanged() -> None:
    state = SearchState(check_in=date(2026, 8, 15), check_out=date(2026, 8, 18))

    result = build_validator().apply(state, SearchPatch(check_out=date(2026, 8, 10)))

    assert [issue.code for issue in result.issues] == [IssueCode.INVALID_DATES]
    assert result.state.check_out == date(2026, 8, 18)


def test_half_specified_stay_is_kept_until_the_other_side_arrives() -> None:
    validator = build_validator()

    first = validator.apply(SearchState(), SearchPatch(check_in=date(2026, 8, 15)))
    assert first.state.check_in == date(2026, 8, 15)
    assert first.state.date_range() is None

    second = validator.apply(first.state, SearchPatch(check_out=date(2026, 8, 18)))
    assert second.state.date_range() is not None


def test_reset_clears_everything() -> None:
    state = SearchState(destination="Haarlem", filters=[AppliedFilter(filter_id="hotel.parking", value=True)])

    result = build_validator().apply(state, SearchPatch(reset=True))

    assert result.state == SearchState()


def test_strength_is_carried_into_the_state() -> None:
    result = build_validator().apply(
        SearchState(),
        SearchPatch(
            operations=[
                FilterOperation(op="add", filter_id="hotel.parking", value=True, strength=FilterStrength.PREFERRED)
            ]
        ),
    )

    assert result.state.filter_by_id("hotel.parking").strength is FilterStrength.PREFERRED
