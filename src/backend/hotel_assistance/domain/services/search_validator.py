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
from hotel_assistance.domain.services.filter_registry import (
    FilterRegistry,
    FilterRegistryError,
    FilterValueError,
)


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

        if patch.destination:
            working.destination = patch.destination.strip()

        self._apply_dates(working, patch, issues)

        if patch.guests is not None:
            working.guests = patch.guests

        # Removals run first so a single message can legally swap one side of
        # a conflicting pair for the other ("no, make it a smoking room").
        ordered = sorted(
            patch.operations,
            key=lambda operation: operation.op is not FilterOperationType.REMOVE,
        )
        for operation in ordered:
            self._apply_operation(working, operation, applied, issues)

        return PatchResult(state=working, applied=applied, issues=issues)

    def _apply_dates(self, state: SearchState, patch: SearchPatch, issues: list[ValidationIssue]) -> None:
        check_in = patch.check_in or state.check_in
        check_out = patch.check_out or state.check_out
        if patch.check_in is None and patch.check_out is None:
            return

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
