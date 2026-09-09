import json
import re
from importlib import resources
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from hotel_assistance.domain.models.filter_definition import FilterDefinition, FilterType

_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "a", "an", "the", "is", "are", "of", "in", "on", "and", "or", "to",
    "for", "with", "at", "this", "that", "have", "has", "do", "does",
}


class FilterRegistryError(Exception):
    """Raised when filter registry data is missing, malformed, or internally inconsistent."""


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

        self._by_id = by_id

    @classmethod
    def from_file(cls, path: str | Path) -> "FilterRegistry":
        try:
            raw = json.loads(Path(path).read_text())
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

    def get(self, filter_id: str) -> FilterDefinition | None:
        return self._by_id.get(filter_id)

    def list_all(self) -> list[FilterDefinition]:
        return list(self._by_id.values())

    def find_candidates(self, text: str, limit: int = 20) -> list[FilterDefinition]:
        """Preselect filters relevant to free-form text via alias/keyword matching.

        Deterministic keyword retrieval, per the registry's guidance to
        preselect candidates before LLM extraction rather than sending the
        entire registry in the prompt.
        """

        needle = text.lower()
        needle_words = set(_WORD_RE.findall(needle)) - _STOPWORDS

        scored: list[tuple[int, FilterDefinition]] = []
        for definition in self._by_id.values():
            terms = [definition.id, definition.description, *definition.aliases]
            score = 0
            for term in terms:
                term_lower = term.lower()
                if term_lower in needle:
                    score += 2
                    continue
                term_words = set(_WORD_RE.findall(term_lower)) - _STOPWORDS
                if term_words & needle_words:
                    score += 1
            if score:
                scored.append((score, definition))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [definition for _, definition in scored[:limit]]

    def validate_value(self, filter_id: str, value: Any) -> None:
        """Validate a candidate filter value against its registry definition.

        Only checks static, registry-level constraints (type, unit-bound
        range). Conflict resolution against the current SearchState is a
        separate, stateful concern.
        """

        definition = self.get(filter_id)
        if definition is None:
            raise FilterRegistryError(f"Unknown filter id: {filter_id}")

        if definition.type == FilterType.BOOLEAN:
            if not isinstance(value, bool):
                raise FilterRegistryError(f"Filter '{filter_id}' expects a boolean value, got {value!r}")
            return

        if not isinstance(value, int | float) or isinstance(value, bool):
            raise FilterRegistryError(f"Filter '{filter_id}' expects a numeric value, got {value!r}")

        bounds = definition.bounds
        if bounds is not None:
            if bounds.min is not None and value < bounds.min:
                raise FilterRegistryError(f"Filter '{filter_id}' value {value} is below minimum {bounds.min}")
            if bounds.max is not None and value > bounds.max:
                raise FilterRegistryError(f"Filter '{filter_id}' value {value} is above maximum {bounds.max}")
