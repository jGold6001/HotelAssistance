"""Deterministic validation and application of search patches.

Every business-critical decision lives here: which operations are legal,
which values are in range, and how conflicts are resolved. The LLM never
participates in these decisions.
"""

from enum import StrEnum

from pydantic import BaseModel, ValidationError

from hotel_assistance.domain.models.applied_filter import AppliedFilter
from hotel_assistance.domain.models.date_range import DateRange
from hotel_assistance.domain.models.filter_operation import (
    FilterOperation,
    FilterOperationType,
)
from hotel_assistance.domain.models.search_patch import SearchPatch
from hotel_assistance.domain.models.search_state import SearchState
from hotel_assistance.domain.models.trip_field import TripField
from hotel_assistance.domain.services.filter_registry import (
    FilterRegistry,
    FilterRegistryError,
    FilterValueError,
)


__all__ = [
    "IssueCode",
    "PatchResult",
    "SearchValidator",
    "TripField",
    "ValidationIssue",
]


class IssueCode(StrEnum):
    UNKNOWN_FILTER = "unknown_filter"
    MISSING_VALUE = "missing_value"
    INVALID_VALUE = "invalid_value"
    CONFLICT = "conflict"
    NOT_APPLIED = "not_applied"
    INVALID_DATES = "invalid_dates"


class ValidationIssue(BaseModel):
    """One rejected part of a patch, with a user-presentable explanation."""

    code: IssueCode
    message: str
    filter_id: str | None = None
    conflicting_filter_id: str | None = None


class PatchResult(BaseModel):
    """Outcome of applying a patch: the new state plus what was refused."""

    state: SearchState
    applied: list[FilterOperation] = []
    applied_trip: list[TripField] = []
    issues: list[ValidationIssue] = []

    @property
    def conflicts(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.code is IssueCode.CONFLICT]


class SearchValidator:
    """Applies a SearchPatch to a SearchState under deterministic rules."""

    def __init__(self, registry: FilterRegistry) -> None:
        self._registry = registry

    def apply(self, state: SearchState, patch: SearchPatch) -> PatchResult:
        working = SearchState() if patch.reset else state.model_copy(deep=True)
        issues: list[ValidationIssue] = []
        applied: list[FilterOperation] = []
        applied_trip: list[TripField] = []

        _apply_destination(working, patch, applied_trip)
        _apply_dates(working, patch, applied_trip, issues)
        _apply_guests(working, patch, applied_trip)

        self_conflicting = self._self_conflicting_filter_ids(patch.operations, issues)

        # Removals run first so a single message can legally swap one side of
        # a conflicting pair for the other ("no, make it a smoking room").
        ordered = sorted(
            patch.operations,
            key=lambda operation: operation.op is not FilterOperationType.REMOVE,
        )
        for operation in ordered:
            if operation.filter_id in self_conflicting:
                continue
            self._apply_operation(working, operation, applied, issues)

        return PatchResult(state=working, applied=applied, applied_trip=applied_trip, issues=issues)

    def _self_conflicting_filter_ids(
        self, operations: list[FilterOperation], issues: list[ValidationIssue]
    ) -> set[str]:
        """Flag a filter the same message asks to set to two different values.

        A message can contradict itself ("pet-friendly, no pets"), producing
        an add/update pair on the same filter_id with opposing values.
        conflicts_with only catches conflicts between distinct filters, so
        without this check the later operation would silently win; instead
        neither value is applied and the user is asked to pick one.
        """

        values_by_filter: dict[str, list] = {}
        for operation in operations:
            if operation.op is FilterOperationType.REMOVE:
                continue
            values_by_filter.setdefault(operation.filter_id, []).append(operation.value)

        conflicting_ids: set[str] = set()
        for filter_id, values in values_by_filter.items():
            if all(value == values[0] for value in values):
                continue
            conflicting_ids.add(filter_id)
            definition = self._registry.get(filter_id)
            description = definition.description if definition else filter_id
            issues.append(
                ValidationIssue(
                    code=IssueCode.CONFLICT,
                    message=(
                        f"You asked for two different values for '{description}' in the "
                        "same message."
                    ),
                    filter_id=filter_id,
                )
            )
        return conflicting_ids

    def _apply_operation(
        self,
        state: SearchState,
        operation: FilterOperation,
        applied: list[FilterOperation],
        issues: list[ValidationIssue],
    ) -> None:
        try:
            definition = self._registry.require(operation.filter_id)
        except FilterRegistryError:
            issues.append(
                ValidationIssue(
                    code=IssueCode.UNKNOWN_FILTER,
                    message=f"'{operation.filter_id}' is not a supported filter.",
                    filter_id=operation.filter_id,
                )
            )
            return

        if operation.op is FilterOperationType.REMOVE:
            existing = state.filter_by_id(definition.id)
            if existing is None:
                issues.append(
                    ValidationIssue(
                        code=IssueCode.NOT_APPLIED,
                        message=f"'{definition.description}' was not set, so there was nothing to remove.",
                        filter_id=definition.id,
                    )
                )
                return
            state.filters = [item for item in state.filters if item.filter_id != definition.id]
            applied.append(operation)
            return

        if operation.value is None:
            issues.append(
                ValidationIssue(
                    code=IssueCode.MISSING_VALUE,
                    message=f"No value was provided for '{definition.description}'.",
                    filter_id=definition.id,
                )
            )
            return

        try:
            self._registry.validate_value(definition.id, operation.value)
        except FilterValueError as exc:
            issues.append(
                ValidationIssue(code=IssueCode.INVALID_VALUE, message=str(exc), filter_id=definition.id)
            )
            return

        conflicting_id = self._find_conflict(state, definition.id, operation.value)
        if conflicting_id is not None:
            conflicting = self._registry.require(conflicting_id)
            issues.append(
                ValidationIssue(
                    code=IssueCode.CONFLICT,
                    message=(
                        f"'{definition.description}' conflicts with '{conflicting.description}', "
                        "which is already active."
                    ),
                    filter_id=definition.id,
                    conflicting_filter_id=conflicting_id,
                )
            )
            return

        state.filters = [item for item in state.filters if item.filter_id != definition.id]
        state.filters.append(
            AppliedFilter(filter_id=definition.id, value=operation.value, strength=operation.strength)
        )
        applied.append(operation)

    def _find_conflict(self, state: SearchState, filter_id: str, value: object) -> str | None:
        """Two filters only conflict when both are actually being asked for.

        A filter explicitly set to ``false`` states an absence and can never
        contradict another request.
        """

        if value is False:
            return None
        for conflicting_id in sorted(self._registry.conflicts_for(filter_id)):
            existing = state.filter_by_id(conflicting_id)
            if existing is not None and existing.value is not False:
                return conflicting_id
        return None


def _apply_destination(state: SearchState, patch: SearchPatch, applied_trip: list[TripField]) -> None:
    """A named destination wins; a hint only clears the superseded one."""

    if patch.destination:
        state.destination = patch.destination.strip()
        applied_trip.append(TripField.DESTINATION)
    elif patch.clear_destination and state.destination is not None:
        state.destination = None
        applied_trip.append(TripField.DESTINATION)


def _apply_dates(
    state: SearchState,
    patch: SearchPatch,
    applied_trip: list[TripField],
    issues: list[ValidationIssue],
) -> None:
    """Apply the date side of a patch, keeping a half-specified stay usable.

    When the patch clears the dates, the surviving side of the current stay is
    not reused: "something in May" means the August check-out is gone too, and
    silently pairing it with a new May check-in would build a range the user
    never asked for.
    """

    if patch.check_in is None and patch.check_out is None:
        if patch.clear_dates and (state.check_in is not None or state.check_out is not None):
            state.check_in = None
            state.check_out = None
            applied_trip.append(TripField.DATES)
        return

    check_in = patch.check_in or (None if patch.clear_dates else state.check_in)
    check_out = patch.check_out or (None if patch.clear_dates else state.check_out)

    if check_in is not None and check_out is not None:
        try:
            DateRange(check_in=check_in, check_out=check_out)
        except ValidationError:
            issues.append(
                ValidationIssue(
                    code=IssueCode.INVALID_DATES,
                    message=(
                        f"Check-out ({check_out.isoformat()}) must be after "
                        f"check-in ({check_in.isoformat()})."
                    ),
                )
            )
            return

    state.check_in = check_in
    state.check_out = check_out
    applied_trip.append(TripField.DATES)


def _apply_guests(state: SearchState, patch: SearchPatch, applied_trip: list[TripField]) -> None:
    if patch.guests is None:
        return
    state.guests = patch.guests
    applied_trip.append(TripField.GUESTS)
