from datetime import date

from hotel_assistance.domain.models import (
    AppliedFilter,
    GuestConfig,
    RangeValue,
    SearchState,
)


def test_default_search_state_is_empty() -> None:
    state = SearchState()

    assert state.destination is None
    assert state.check_in is None
    assert state.check_out is None
    assert state.date_range() is None
    assert state.guests is None
    assert state.filters == []


def test_search_state_can_hold_applied_filters() -> None:
    state = SearchState(filters=[AppliedFilter(filter_id="room.size_m2", value=RangeValue(min=30))])

    assert state.filter_by_id("room.size_m2").value == RangeValue(min=30)
    assert state.filter_by_id("hotel.parking") is None


def test_date_range_is_exposed_once_both_sides_are_known() -> None:
    state = SearchState(check_in=date(2026, 8, 15))
    assert state.date_range() is None

    state.check_out = date(2026, 8, 18)
    assert state.date_range().check_out == date(2026, 8, 18)


def test_search_is_ready_only_with_destination_dates_and_guests() -> None:
    state = SearchState(destination="Haarlem", check_in=date(2026, 8, 15), check_out=date(2026, 8, 18))
    assert state.is_ready_for_search() is False

    state.guests = GuestConfig(adults=2)
    assert state.is_ready_for_search() is True
