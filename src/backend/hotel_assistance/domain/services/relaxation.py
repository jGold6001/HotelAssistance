"""Deterministic filter-relaxation suggestions for zero-result searches.

Suggestions are derived only from filters the user actually set and from the
registry. Nothing about hotels, prices, or availability is invented here; the
zero-result signal itself must come from the hotel backend.
"""

from pydantic import BaseModel

from hotel_assistance.domain.models.filter_definition import FilterType
from hotel_assistance.domain.models.filter_value import RangeValue
from hotel_assistance.domain.models.search_state import SearchState
from hotel_assistance.domain.models.strength import FilterStrength
from hotel_assistance.domain.services.filter_registry import FilterRegistry


class RelaxationSuggestion(BaseModel):
    filter_id: str
    label: str
    reason: str


def suggest_relaxations(
    state: SearchState,
    registry: FilterRegistry,
    limit: int = 3,
) -> list[RelaxationSuggestion]:
    """Rank the current filters by how cheap they are to give up.

    Order: soft preferences first, then numeric constraints (which can be
    widened rather than dropped), then hard requirements.
    """

    ranked: list[tuple[int, RelaxationSuggestion]] = []
    for applied in state.filters:
        definition = registry.get(applied.filter_id)
        if definition is None:
            continue

        if applied.strength is FilterStrength.PREFERRED:
            priority = 0
            reason = "you marked it as a preference rather than a requirement"
        elif definition.type is FilterType.RANGE:
            priority = 1
            reason = "widening a numeric limit usually opens up more properties"
        else:
            priority = 2
            reason = "dropping it is the remaining way to widen the search"

        label = definition.description
        if definition.type is FilterType.RANGE and isinstance(applied.value, RangeValue):
            label = f"{definition.description} ({applied.value.describe(definition.unit)})"

        ranked.append((priority, RelaxationSuggestion(filter_id=definition.id, label=label, reason=reason)))

    ranked.sort(key=lambda item: (item[0], item[1].filter_id))
    return [suggestion for _, suggestion in ranked[:limit]]
