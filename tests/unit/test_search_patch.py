from datetime import date

from hotel_assistance.domain.models import (
    FilterOperation,
    FilterOperationType,
    RangeValue,
    SearchPatch,
)


def test_empty_patch_has_no_effect_fields_set() -> None:
    patch = SearchPatch()

    assert patch.destination is None
    assert patch.check_in is None
    assert patch.check_out is None
    assert patch.guests is None
    assert patch.operations == []
    assert patch.reset is False
    assert patch.is_empty() is True


def test_patch_can_carry_filter_operations() -> None:
    patch = SearchPatch(
        operations=[
            FilterOperation(op=FilterOperationType.ADD, filter_id="room.size_m2", value=RangeValue(min=30)),
            FilterOperation(op=FilterOperationType.REMOVE, filter_id="hotel.parking"),
        ]
    )

    assert [operation.op for operation in patch.operations] == [
        FilterOperationType.ADD,
        FilterOperationType.REMOVE,
    ]
    assert patch.is_empty() is False


def test_a_patch_that_only_sets_dates_is_not_empty() -> None:
    assert SearchPatch(check_in=date(2026, 8, 15)).is_empty() is False
