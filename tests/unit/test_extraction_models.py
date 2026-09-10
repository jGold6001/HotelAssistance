import pytest
from hotel_assistance.domain.models.extraction import ExtractedFilter
from hotel_assistance.domain.models.filter_value import RangeValue
from pydantic import ValidationError


def test_boolean_filter_requires_boolean_value() -> None:
    with pytest.raises(ValidationError):
        ExtractedFilter(filter_id="hotel.parking", op="add", type="boolean", strength="required")


def test_boolean_filter_rejects_a_range_value() -> None:
    with pytest.raises(ValidationError):
        ExtractedFilter(
            filter_id="hotel.parking",
            op="add",
            type="boolean",
            strength="required",
            boolean_value=True,
            range_value=RangeValue(min=1),
        )


def test_range_filter_requires_a_range_value() -> None:
    with pytest.raises(ValidationError):
        ExtractedFilter(filter_id="rating.stars", op="add", type="range", strength="required")


def test_removal_ignores_any_attached_value() -> None:
    extracted = ExtractedFilter(
        filter_id="hotel.parking", op="remove", type="boolean", strength="required", boolean_value=True
    )

    assert extracted.boolean_value is None
    assert extracted.range_value is None
