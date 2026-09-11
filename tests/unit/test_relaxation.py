from hotel_assistance.domain.models.applied_filter import AppliedFilter
from hotel_assistance.domain.models.filter_definition import FilterDefinition
from hotel_assistance.domain.models.filter_value import RangeValue
from hotel_assistance.domain.models.search_state import SearchState
from hotel_assistance.domain.services.filter_registry import FilterRegistry
from hotel_assistance.domain.services.relaxation import suggest_relaxations


def build_registry() -> FilterRegistry:
    return FilterRegistry(
        [
            FilterDefinition(id="hotel.parking", type="boolean", description="Parking"),
            FilterDefinition(id="hotel.spa", type="boolean", description="Spa"),
            FilterDefinition(id="room.size_m2", type="range", description="Room floor area", unit="m2"),
        ]
    )


def test_preferences_are_suggested_before_requirements() -> None:
    state = SearchState(
        filters=[
            AppliedFilter(filter_id="hotel.parking", value=True),
            AppliedFilter(filter_id="room.size_m2", value=RangeValue(min=60)),
            AppliedFilter(filter_id="hotel.spa", value=True, strength="preferred"),
        ]
    )

    suggestions = suggest_relaxations(state, build_registry())

    assert [item.filter_id for item in suggestions] == ["hotel.spa", "room.size_m2", "hotel.parking"]


def test_range_suggestions_show_the_current_limit() -> None:
    state = SearchState(filters=[AppliedFilter(filter_id="room.size_m2", value=RangeValue(min=60))])

    suggestions = suggest_relaxations(state, build_registry())

    assert suggestions[0].label == "Room floor area (at least 60 m2)"


def test_nothing_is_suggested_for_an_empty_state() -> None:
    assert suggest_relaxations(SearchState(), build_registry()) == []


def test_suggestions_are_limited() -> None:
    state = SearchState(
        filters=[
            AppliedFilter(filter_id="hotel.parking", value=True),
            AppliedFilter(filter_id="hotel.spa", value=True),
            AppliedFilter(filter_id="room.size_m2", value=RangeValue(min=60)),
        ]
    )

    assert len(suggest_relaxations(state, build_registry(), limit=2)) == 2
