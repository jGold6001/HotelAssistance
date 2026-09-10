from datetime import date

from hotel_assistance.application.patch_builder import build_patch
from hotel_assistance.domain.models.applied_filter import AppliedFilter
from hotel_assistance.domain.models.candidate_filter import CandidateFilter
from hotel_assistance.domain.models.extraction import (
    ExtractedFilter,
    ExtractionResult,
    GuestCounts,
    TripDetails,
)
from hotel_assistance.domain.models.filter_definition import FilterDefinition
from hotel_assistance.domain.models.filter_value import RangeValue
from hotel_assistance.domain.models.guest_config import GuestConfig
from hotel_assistance.domain.models.search_state import SearchState
from hotel_assistance.domain.services.filter_registry import FilterRegistry
from hotel_assistance.domain.services.search_validator import IssueCode

PARKING = FilterDefinition(id="hotel.parking", type="boolean", description="Parking")
STARS = FilterDefinition(id="rating.stars", type="range", description="Star rating", unit="stars")


def build_registry() -> FilterRegistry:
    return FilterRegistry([PARKING, STARS])


def candidates() -> list[CandidateFilter]:
    return [
        CandidateFilter(definition=PARKING, score=0.9),
        CandidateFilter(definition=STARS, score=0.8),
    ]


def test_boolean_and_range_filters_become_operations() -> None:
    result = ExtractionResult(
        filters=[
            ExtractedFilter(
                filter_id="hotel.parking", op="add", type="boolean", strength="required", boolean_value=True
            ),
            ExtractedFilter(
                filter_id="rating.stars",
                op="add",
                type="range",
                strength="preferred",
                range_value=RangeValue(min=4),
            ),
        ]
    )

    patch, issues = build_patch(result, candidates(), build_registry(), SearchState())

    assert issues == []
    assert [operation.filter_id for operation in patch.operations] == ["hotel.parking", "rating.stars"]
    assert patch.operations[0].value is True
    assert patch.operations[1].value == RangeValue(min=4)
    assert patch.operations[1].strength == "preferred"


def test_filter_outside_the_candidate_set_is_dropped() -> None:
    result = ExtractionResult(
        filters=[
            ExtractedFilter(
                filter_id="hotel.pool_on_mars",
                op="add",
                type="boolean",
                strength="required",
                boolean_value=True,
            )
        ]
    )

    patch, issues = build_patch(result, candidates(), build_registry(), SearchState())

    assert patch.operations == []
    assert [issue.code for issue in issues] == [IssueCode.UNKNOWN_FILTER]


def test_removal_may_target_an_applied_filter_that_retrieval_missed() -> None:
    state = SearchState(filters=[AppliedFilter(filter_id="hotel.parking", value=True)])
    result = ExtractionResult(
        filters=[
            ExtractedFilter(filter_id="hotel.parking", op="remove", type="boolean", strength="required")
        ]
    )

    patch, issues = build_patch(result, [], build_registry(), state)

    assert issues == []
    assert [operation.op for operation in patch.operations] == ["remove"]


def test_type_mismatch_is_dropped() -> None:
    result = ExtractionResult(
        filters=[
            ExtractedFilter(
                filter_id="rating.stars", op="add", type="boolean", strength="required", boolean_value=True
            )
        ]
    )

    patch, issues = build_patch(result, candidates(), build_registry(), SearchState())

    assert patch.operations == []
    assert [issue.code for issue in issues] == [IssueCode.INVALID_VALUE]


def test_iso_dates_are_parsed() -> None:
    result = ExtractionResult(trip=TripDetails(check_in="2026-08-15", check_out="2026-08-18"))

    patch, issues = build_patch(result, candidates(), build_registry(), SearchState())

    assert issues == []
    assert patch.check_in == date(2026, 8, 15)
    assert patch.check_out == date(2026, 8, 18)


def test_unparseable_date_is_reported_and_ignored() -> None:
    result = ExtractionResult(trip=TripDetails(check_in="15 Aug"))

    patch, issues = build_patch(result, candidates(), build_registry(), SearchState())

    assert patch.check_in is None
    assert [issue.code for issue in issues] == [IssueCode.INVALID_DATES]


def test_partial_guest_update_keeps_the_known_side() -> None:
    state = SearchState(guests=GuestConfig(adults=2, children=1))
    result = ExtractionResult(trip=TripDetails(guests=GuestCounts(children=2)))

    patch, issues = build_patch(result, candidates(), build_registry(), state)

    assert issues == []
    assert patch.guests == GuestConfig(adults=2, children=2)


def test_impossible_guest_count_is_reported_and_ignored() -> None:
    result = ExtractionResult(trip=TripDetails(guests=GuestCounts(adults=0)))

    patch, issues = build_patch(result, candidates(), build_registry(), SearchState())

    assert patch.guests is None
    assert [issue.code for issue in issues] == [IssueCode.INVALID_VALUE]


def test_reset_request_is_carried_through() -> None:
    patch, _ = build_patch(
        ExtractionResult(reset_requested=True), candidates(), build_registry(), SearchState()
    )

    assert patch.reset is True
