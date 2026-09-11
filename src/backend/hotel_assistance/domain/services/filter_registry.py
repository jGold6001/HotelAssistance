import json
from importlib import resources
from pathlib import Path

from pydantic import ValidationError

from hotel_assistance.domain.models.filter_definition import (
    FilterDefinition,
    FilterType,
)
from hotel_assistance.domain.models.filter_value import FilterValue, RangeValue


class FilterRegistryError(Exception):
    """Raised when filter registry data is missing, malformed, or internally inconsistent."""


class FilterValueError(Exception):
    """Raised when a value does not satisfy its filter's registry definition."""


class FilterRegistry:
    """Canonical source of supported hotel-search filters.

    Never persist or trust arbitrary LLM-generated filter IDs; only IDs known
    to this registry are valid targets for a FilterOperation.
    """

    def __init__(self, definitions: list[FilterDefinition]) -> None:
        by_id: dict[str, FilterDefinition] = {}
        for definition in definitions:
            if definition.id in by_id:
                raise FilterRegistryError(f"Duplicate filter id in registry: {definition.id}")
            by_id[definition.id] = definition

        for definition in by_id.values():
            for conflict_id in definition.conflicts_with:
                if conflict_id not in by_id:
                    raise FilterRegistryError(
                        f"Filter '{definition.id}' declares conflicts_with unknown filter id '{conflict_id}'"
                    )
            if definition.type is FilterType.RANGE and definition.unit is None:
                raise FilterRegistryError(f"Range filter '{definition.id}' must declare a unit")

        self._by_id = by_id

    @classmethod
    def from_file(cls, path: str | Path) -> "FilterRegistry":
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FilterRegistryError(f"Could not read filter registry file '{path}': {exc}") from exc

        try:
            definitions = [FilterDefinition.model_validate(item) for item in raw]
        except ValidationError as exc:
            raise FilterRegistryError(f"Invalid filter registry data in '{path}': {exc}") from exc

        return cls(definitions)

    @classmethod
    def default(cls) -> "FilterRegistry":
        """Load the built-in registry shipped with the package."""

        registry_path = resources.files("hotel_assistance.domain.registry").joinpath("filters.json")
        with resources.as_file(registry_path) as path:
            return cls.from_file(path)

    def __contains__(self, filter_id: str) -> bool:
        return filter_id in self._by_id

    def __len__(self) -> int:
        return len(self._by_id)

    def get(self, filter_id: str) -> FilterDefinition | None:
        return self._by_id.get(filter_id)

    def require(self, filter_id: str) -> FilterDefinition:
        definition = self._by_id.get(filter_id)
        if definition is None:
            raise FilterRegistryError(f"Unknown filter id: {filter_id}")
        return definition

    def list_all(self) -> list[FilterDefinition]:
        return list(self._by_id.values())

    def conflicts_for(self, filter_id: str) -> set[str]:
        """Return conflicting IDs symmetrically, regardless of which side declares them."""

        definition = self.get(filter_id)
        declared = set(definition.conflicts_with) if definition else set()
        reverse = {other.id for other in self._by_id.values() if filter_id in other.conflicts_with}
        return declared | reverse

    def validate_value(self, filter_id: str, value: FilterValue) -> None:
        """Validate a candidate filter value against its registry definition.

        Only checks static, registry-level constraints (type match, bounds).
        Conflict resolution against the current SearchState is a separate,
        stateful concern owned by SearchValidator.
        """

        definition = self.require(filter_id)

        if definition.type is FilterType.BOOLEAN:
            if not isinstance(value, bool):
                raise FilterValueError(f"Filter '{filter_id}' expects a boolean value, got {value!r}")
            return

        if not isinstance(value, RangeValue):
            raise FilterValueError(f"Filter '{filter_id}' expects a range value, got {value!r}")

        bounds = definition.bounds
        if bounds is None:
            return

        unit = f" {definition.unit}" if definition.unit else ""
        for side in (value.min, value.max):
            if side is None:
                continue
            if bounds.min is not None and side < bounds.min:
                raise FilterValueError(
                    f"Filter '{filter_id}' value {side}{unit} is below the allowed minimum {bounds.min}{unit}"
                )
            if bounds.max is not None and side > bounds.max:
                raise FilterValueError(
                    f"Filter '{filter_id}' value {side}{unit} is above the allowed maximum {bounds.max}{unit}"
                )
