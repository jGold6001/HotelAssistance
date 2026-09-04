from hotel_assistance.domain.models import AppliedFilter, SearchState


def test_default_search_state_is_empty() -> None:
    state = SearchState()

    assert state.destination is None
    assert state.dates is None
    assert state.guests is None
    assert state.filters == []


def test_search_state_can_hold_applied_filters() -> None:
    state = SearchState(filters=[AppliedFilter(filter_id="room.size_m2", value={"min": 30})])

    assert state.filters[0].filter_id == "room.size_m2"
