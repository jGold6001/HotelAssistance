"""Deterministic translation of LLM output into a SearchPatch.

This is the boundary where untrusted model output stops being trusted at all:
IDs are checked against the retrieved candidate set and the registry, values
are checked against the declared filter type, and dates are really parsed.
Anything that does not survive is dropped with an explicit issue.
"""

import re
from datetime import date

from pydantic import ValidationError

from hotel_assistance.domain.models.candidate_filter import CandidateFilter
from hotel_assistance.domain.models.extraction import ExtractedFilter, ExtractionResult
from hotel_assistance.domain.models.filter_operation import (
    FilterOperation,
    FilterOperationType,
)
from hotel_assistance.domain.models.filter_value import FilterValue
from hotel_assistance.domain.models.guest_config import GuestConfig
from hotel_assistance.domain.models.search_patch import SearchPatch
from hotel_assistance.domain.models.search_state import SearchState
from hotel_assistance.domain.services.filter_registry import FilterRegistry
from hotel_assistance.domain.services.search_validator import IssueCode, ValidationIssue


def build_patch(
    result: ExtractionResult,
    candidates: list[CandidateFilter],
    registry: FilterRegistry,
    state: SearchState,
) -> tuple[SearchPatch, list[ValidationIssue]]:
    """Build a SearchPatch from an ExtractionResult, discarding what is unusable."""

    issues: list[ValidationIssue] = []
    allowed_ids = {candidate.definition.id for candidate in candidates}
    applied_ids = {applied.filter_id for applied in state.filters}

    operations: list[FilterOperation] = []
    for extracted in result.filters:
        # A removal may legitimately target a filter that retrieval did not
        # surface this turn, as long as it is actually part of the state.
        is_removal = extracted.op is FilterOperationType.REMOVE
        if extracted.filter_id not in allowed_ids and not (is_removal and extracted.filter_id in applied_ids):
            issues.append(
                ValidationIssue(
                    code=IssueCode.UNKNOWN_FILTER,
                    message=f"Ignored '{extracted.filter_id}': it is not one of the filters offered to the model.",
                    filter_id=extracted.filter_id,
                )
            )
            continue

        definition = registry.get(extracted.filter_id)
        if definition is None:
            issues.append(
                ValidationIssue(
                    code=IssueCode.UNKNOWN_FILTER,
                    message=f"Ignored '{extracted.filter_id}': it is not in the filter registry.",
                    filter_id=extracted.filter_id,
                )
            )
            continue

        if not is_removal and extracted.type is not definition.type:
            issues.append(
                ValidationIssue(
                    code=IssueCode.INVALID_VALUE,
                    message=(
                        f"Ignored '{extracted.filter_id}': the model treated it as {extracted.type.value}, "
                        f"but it is a {definition.type.value} filter."
                    ),
                    filter_id=extracted.filter_id,
                )
            )
            continue

        operations.append(
            FilterOperation(
                op=extracted.op,
                filter_id=extracted.filter_id,
                value=None if is_removal else _operation_value(extracted),
                strength=extracted.strength,
            )
        )

    check_in, check_in_issue = _parse_date(result.trip.check_in, "check-in")
    check_out, check_out_issue = _parse_date(result.trip.check_out, "check-out")
    issues.extend(issue for issue in (check_in_issue, check_out_issue) if issue is not None)

    patch = SearchPatch(
        destination=result.trip.destination or None,
        check_in=check_in,
        check_out=check_out,
        guests=_build_guests(result, state, issues),
        operations=operations,
        reset=result.reset_requested,
        # A hint means the user moved this detail without naming a new value,
        # so the old one is no longer what they are asking for. The validator
        # still prefers a concrete value when the message carried both.
        clear_destination=bool(_clean(result.trip.destination_hint)),
        clear_dates=bool(_clean(result.trip.date_hint)),
    )
    return patch, issues


def clean_unmapped_requests(result: ExtractionResult) -> list[str]:
    """Keep only the requests that are genuinely unsupported filters.

    A trip detail the assistant is already asking about ("something in May")
    is not an unsupported feature, and reporting it as one buries the
    follow-up question the user actually has to answer. Duplicates and blanks
    are dropped for the same reason: the list is read by a human.
    """

    hints = [hint for hint in map(_clean, (result.trip.destination_hint, result.trip.date_hint)) if hint]

    kept: list[str] = []
    seen: set[str] = set()
    for raw in result.unmapped_requests:
        text = _clean(raw)
        if text is None:
            continue
        key = text.lower()
        if key in seen or any(_mentions(text, hint) for hint in hints):
            continue
        seen.add(key)
        kept.append(text)
    return kept


def _mentions(text: str, hint: str) -> bool:
    """Whole-word containment, so "May" does not match "maybe"."""

    return re.search(rf"\b{re.escape(hint)}\b", text, flags=re.IGNORECASE) is not None


def _clean(raw: str | None) -> str | None:
    """Collapse model whitespace and treat an empty string as absent."""

    if raw is None:
        return None
    text = " ".join(raw.split())
    return text or None


def _operation_value(extracted: ExtractedFilter) -> FilterValue:
    """Flatten the model's two value slots into the single domain value.

    ``ExtractedFilter`` validation has already guaranteed that exactly one of
    them is set for a non-removal operation.
    """

    if extracted.boolean_value is not None:
        return extracted.boolean_value
    assert extracted.range_value is not None
    return extracted.range_value


def _parse_date(raw: str | None, label: str) -> tuple[date | None, ValidationIssue | None]:
    if not raw:
        return None, None
    try:
        return date.fromisoformat(raw.strip()), None
    except ValueError:
        return None, ValidationIssue(
            code=IssueCode.INVALID_DATES,
            message=f"Could not read the {label} date '{raw}'. Please give it as a full calendar date.",
        )


def _build_guests(
    result: ExtractionResult,
    state: SearchState,
    issues: list[ValidationIssue],
) -> GuestConfig | None:
    guests = result.trip.guests
    if guests is None or (guests.adults is None and guests.children is None):
        return None

    current = state.guests
    adults = guests.adults if guests.adults is not None else (current.adults if current else 1)
    children = guests.children if guests.children is not None else (current.children if current else 0)
    try:
        return GuestConfig(adults=adults, children=children)
    except ValidationError:
        issues.append(
            ValidationIssue(
                code=IssueCode.INVALID_VALUE,
                message=f"Ignored an impossible guest count ({adults} adults, {children} children).",
            )
        )
        return None
