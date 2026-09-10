import json

import pytest
from hotel_assistance.domain.models.filter_definition import FilterDefinition
from hotel_assistance.domain.models.filter_value import RangeValue
from hotel_assistance.domain.services.filter_registry import (
    FilterRegistry,
    FilterRegistryError,
    FilterValueError,
)


def _write_registry(tmp_path, definitions: list[dict]) -> str:
    path = tmp_path / "filters.json"
    path.write_text(json.dumps(definitions))
    return str(path)


def test_default_registry_loads_without_error() -> None:
    registry = FilterRegistry.default()

    assert len(registry) > 400
    assert "hotel.parking" in registry
    assert "room.size_m2" in registry


def test_get_returns_none_for_unknown_id() -> None:
    assert FilterRegistry.default().get("does.not.exist") is None


def test_require_raises_for_unknown_id() -> None:
    with pytest.raises(FilterRegistryError):
        FilterRegistry.default().require("does.not.exist")


def test_duplicate_filter_id_raises() -> None:
    definitions = [
        FilterDefinition(id="hotel.parking", type="boolean", description="a"),
        FilterDefinition(id="hotel.parking", type="boolean", description="b"),
    ]

    with pytest.raises(FilterRegistryError):
        FilterRegistry(definitions)


def test_conflicts_with_unknown_id_raises() -> None:
    definitions = [
        FilterDefinition(
            id="hotel.designated_smoking_area",
            type="boolean",
            description="Smoking area",
            conflicts_with=["hotel.does_not_exist"],
        ),
    ]

    with pytest.raises(FilterRegistryError):
        FilterRegistry(definitions)


def test_range_filter_without_unit_raises() -> None:
    definitions = [FilterDefinition(id="room.size_m2", type="range", description="Room size")]

    with pytest.raises(FilterRegistryError):
        FilterRegistry(definitions)


def test_conflicts_are_symmetric_even_when_declared_on_one_side() -> None:
    definitions = [
        FilterDefinition(id="a", type="boolean", description="A", conflicts_with=["b"]),
        FilterDefinition(id="b", type="boolean", description="B"),
    ]
    registry = FilterRegistry(definitions)

    assert registry.conflicts_for("a") == {"b"}
    assert registry.conflicts_for("b") == {"a"}


def test_from_file_rejects_malformed_data(tmp_path) -> None:
    path = _write_registry(tmp_path, [{"id": "bad", "type": "not-a-type", "description": "x"}])

    with pytest.raises(FilterRegistryError):
        FilterRegistry.from_file(path)


def test_from_file_rejects_missing_file(tmp_path) -> None:
    with pytest.raises(FilterRegistryError):
        FilterRegistry.from_file(tmp_path / "missing.json")


def test_validate_value_boolean_accepts_bool() -> None:
    FilterRegistry.default().validate_value("hotel.parking", True)


def test_validate_value_boolean_rejects_range() -> None:
    with pytest.raises(FilterValueError):
        FilterRegistry.default().validate_value("hotel.parking", RangeValue(min=1))


def test_validate_value_range_accepts_within_bounds() -> None:
    FilterRegistry.default().validate_value("rating.stars", RangeValue(min=4))


def test_validate_value_range_rejects_below_min() -> None:
    with pytest.raises(FilterValueError):
        FilterRegistry.default().validate_value("rating.stars", RangeValue(min=0))


def test_validate_value_range_rejects_above_max() -> None:
    with pytest.raises(FilterValueError):
        FilterRegistry.default().validate_value("rating.stars", RangeValue(max=6))


def test_validate_value_range_rejects_bool() -> None:
    with pytest.raises(FilterValueError):
        FilterRegistry.default().validate_value("rating.stars", True)


def test_validate_value_unknown_filter_id_raises() -> None:
    with pytest.raises(FilterRegistryError):
        FilterRegistry.default().validate_value("does.not.exist", True)
