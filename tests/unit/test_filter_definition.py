import pytest
from hotel_assistance.domain.models.filter_definition import (
    FilterDefinition,
    FilterType,
    RangeBounds,
)
from pydantic import ValidationError


def test_boolean_filter_definition_defaults() -> None:
    definition = FilterDefinition(id="amenity.wifi", type=FilterType.BOOLEAN, description="Free wifi")

    assert definition.aliases == []
    assert definition.unit is None
    assert definition.bounds is None
    assert definition.conflicts_with == []


def test_range_filter_definition_with_bounds_and_unit() -> None:
    definition = FilterDefinition(
        id="rating.stars",
        type=FilterType.RANGE,
        description="Star rating",
        unit="stars",
        bounds=RangeBounds(min=1, max=5),
    )

    assert definition.bounds is not None
    assert definition.bounds.min == 1
    assert definition.bounds.max == 5


def test_invalid_filter_type_rejected() -> None:
    with pytest.raises(ValidationError):
        FilterDefinition(id="x", type="not-a-type", description="x")
