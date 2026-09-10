"""Builds the assistant's reply from the deterministic outcome.

The reply is assembled from what actually happened - applied operations,
rejected ones, the resulting state and the backend's offer count - so it can
never claim a filter was set when validation refused it. Only the
clarification question itself comes from the LLM, because phrasing a question
is a language task.
"""

from hotel_assistance.domain.models.filter_operation import (
    FilterOperation,
    FilterOperationType,
)
from hotel_assistance.domain.models.filter_value import RangeValue
from hotel_assistance.domain.models.search_state import SearchState
from hotel_assistance.domain.services.filter_registry import FilterRegistry
from hotel_assistance.domain.services.relaxation import RelaxationSuggestion
from hotel_assistance.domain.services.search_validator import IssueCode, ValidationIssue

OUT_OF_SCOPE_REPLY = (
    "I can only help with hotel-search filters - destination, dates, guests, "
    "and property or room features. Tell me what you are looking for in a hotel "
    "and I will set the search up."
)

MISSING_LABELS = {
    "destination": "where you want to stay",
    "dates": "your check-in and check-out dates",
    "guests": "how many people are travelling",
}


def compose_reply(
    state: SearchState,
    registry: FilterRegistry,
    applied: list[FilterOperation],
    issues: list[ValidationIssue],
    unmapped_requests: list[str],
    missing_trip_info: list[str],
    clarification_question: str | None,
    available_offers_count: int | None,
    relaxations: list[RelaxationSuggestion],
    was_reset: bool,
) -> str:
    parts: list[str] = []

    if was_reset:
        parts.append("Cleared the search. Starting fresh.")

    parts.extend(_describe_applied(applied, registry))
    parts.extend(issue.message for issue in issues if issue.code is not IssueCode.NOT_APPLIED)

    conflicts = [issue for issue in issues if issue.code is IssueCode.CONFLICT]
    if conflicts:
        parts.append("Tell me which of the two you want to keep and I will switch it over.")

    if unmapped_requests:
        listed = "; ".join(unmapped_requests)
        parts.append(f"I could not map these to a supported filter, so they are not part of the search: {listed}.")

    if available_offers_count == 0:
        parts.append("The hotel backend finds no offers for this search.")
        if relaxations:
            options = "; ".join(f"{item.label} - {item.reason}" for item in relaxations)
            parts.append(f"You could relax: {options}.")
    elif available_offers_count is not None:
        parts.append(f"The hotel backend currently matches {available_offers_count} offers.")

    if clarification_question:
        parts.append(clarification_question)
    elif missing_trip_info:
        needed = [MISSING_LABELS[item] for item in missing_trip_info if item in MISSING_LABELS]
        if needed:
            parts.append(f"To run the search I still need {_join_readable(needed)}.")

    if not parts:
        parts.append("I did not find anything to change in the search. Could you say a bit more about what you want?")

    return " ".join(parts)


def _describe_applied(applied: list[FilterOperation], registry: FilterRegistry) -> list[str]:
    """Report the three outcomes separately.

    Dropping a filter and requiring its absence are different search states, so
    they must not be described with the same word.
    """

    added: list[str] = []
    removed: list[str] = []
    excluded: list[str] = []
    for operation in applied:
        definition = registry.get(operation.filter_id)
        if definition is None:
            continue
        if operation.op is FilterOperationType.REMOVE:
            removed.append(definition.description)
        elif isinstance(operation.value, RangeValue):
            added.append(f"{definition.description} ({operation.value.describe(definition.unit)})")
        elif operation.value is False:
            excluded.append(definition.description)
        else:
            added.append(definition.description)

    parts: list[str] = []
    if added:
        parts.append(f"Applied: {_join_readable(added)}.")
    if removed:
        parts.append(f"Removed: {_join_readable(removed)}.")
    if excluded:
        parts.append(f"Excluding properties with: {_join_readable(excluded)}.")
    return parts


def _join_readable(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"
