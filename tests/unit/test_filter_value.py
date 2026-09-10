import pytest
from hotel_assistance.domain.models.filter_value import RangeValue
from pydantic import ValidationError


def test_range_value_requires_at_least_one_bound() -> None:
    with pytest.raises(ValidationError):
        RangeValue()


def test_range_value_rejects_inverted_bounds() -> None:
    with pytest.raises(ValidationError):
        RangeValue(min=50, max=10)


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        (RangeValue(min=30), "m2", "at least 30 m2"),
        (RangeValue(min=30), None, "at least 30"),
        (RangeValue(max=120), "EUR", "at most 120 EUR"),
        (RangeValue(min=3, max=5), "stars", "3-5 stars"),
        (RangeValue(min=1.5), "km", "at least 1.5 km"),
    ],
)
def test_describe_renders_human_readable_bounds(value: RangeValue, unit: str, expected: str) -> None:
    assert value.describe(unit) == expected
