import json

import pytest

from hotel_assistance.domain.models.filter_definition import FilterDefinition
from hotel_assistance.domain.services.filter_registry import FilterRegistry, FilterRegistryError


def _write_registry(tmp_path, definitions: list[dict]) -> str:
    path = tmp_path / "filters.json"
    path.write_text(json.dumps(definitions))
    return str(path)


def test_default_registry_loads_without_error() -> None:
    registry = FilterRegistry.default()

    assert len(registry.list_all()) > 0
    assert "amenity.wifi" in registry


def test_get_returns_none_for_unknown_id() -> None:
    registry = FilterRegistry.default()

    assert registry.get("does.not.exist") is None


def test_duplicate_filter_id_raises() -> None:
    definitions = [
        FilterDefinition(id="amenity.wifi", type="boolean", description="a"),
        FilterDefinition(id="amenity.wifi", type="boolean", description="b"),
    ]

    with pytest.raises(FilterRegistryError):
        FilterRegistry(definitions)


def test_conflicts_with_unknown_id_raises() -> None:
    definitions = [
        FilterDefinition(
            id="room.smoking_allowed",
            type="boolean",
            description="Smoking allowed",
            conflicts_with=["room.does_not_exist"],
        ),
    ]

    with pytest.raises(FilterRegistryError):
        FilterRegistry(definitions)


def test_from_file_rejects_malformed_data(tmp_path) -> None:
    path = _write_registry(tmp_path, [{"id": "bad", "type": "not-a-type", "description": "x"}])

    with pytest.raises(FilterRegistryError):
        FilterRegistry.from_file(path)


def test_from_file_rejects_missing_file(tmp_path) -> None:
    with pytest.raises(FilterRegistryError):
        FilterRegistry.from_file(tmp_path / "missing.json")


def test_find_candidates_matches_alias() -> None:
    registry = FilterRegistry.default()

    candidates = registry.find_candidates("Does the hotel have a swimming pool and wifi?")

    ids = {definition.id for definition in candidates}
    assert "amenity.pool" in ids
    assert "amenity.wifi" in ids


def test_find_candidates_returns_empty_for_unrelated_text() -> None:
    registry = FilterRegistry.default()

    assert registry.find_candidates("what is the capital of France") == []


def test_validate_value_boolean_accepts_bool() -> None:
    registry = FilterRegistry.default()

    registry.validate_value("amenity.wifi", True)


def test_validate_value_boolean_rejects_non_bool() -> None:
    registry = FilterRegistry.default()

    with pytest.raises(FilterRegistryError):
        registry.validate_value("amenity.wifi", "yes")


def test_validate_value_range_accepts_within_bounds() -> None:
    registry = FilterRegistry.default()

    registry.validate_value("rating.stars", 4)


def test_validate_value_range_rejects_below_min() -> None:
    registry = FilterRegistry.default()

    with pytest.raises(FilterRegistryError):
        registry.validate_value("rating.stars", 0)


def test_validate_value_range_rejects_above_max() -> None:
    registry = FilterRegistry.default()

    with pytest.raises(FilterRegistryError):
        registry.validate_value("rating.stars", 6)


def test_validate_value_range_rejects_non_numeric() -> None:
    registry = FilterRegistry.default()

    with pytest.raises(FilterRegistryError):
        registry.validate_value("rating.stars", "five")


def test_validate_value_unknown_filter_id_raises() -> None:
    registry = FilterRegistry.default()

    with pytest.raises(FilterRegistryError):
        registry.validate_value("does.not.exist", True)
