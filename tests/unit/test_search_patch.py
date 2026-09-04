from hotel_assistance.domain.models import FilterOperation, FilterOperationType, SearchPatch


def test_empty_patch_has_no_effect_fields_set() -> None:
    patch = SearchPatch()

    assert patch.destination is None
    assert patch.dates is None
    assert patch.guests is None
    assert patch.operations == []
    assert patch.clarification_needed is None


def test_patch_can_carry_filter_operations() -> None:
    patch = SearchPatch(
        operations=[
            FilterOperation(op=FilterOperationType.ADD, filter_id="room.size_m2", value={"min": 30}),
            FilterOperation(op=FilterOperationType.REMOVE, filter_id="hotel.free_parking"),
        ]
    )

    assert len(patch.operations) == 2
    assert patch.operations[0].op == FilterOperationType.ADD
    assert patch.operations[1].op == FilterOperationType.REMOVE
