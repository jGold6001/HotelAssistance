"""Transport models for the chat API.

Kept separate from domain models so the wire format can present a flattened,
UI-friendly view without leaking presentation concerns into the domain.
"""

from datetime import date

from pydantic import BaseModel, Field

from hotel_assistance.application.chat_orchestrator import ChatResult
from hotel_assistance.domain.models.filter_value import RangeValue
from hotel_assistance.domain.models.pending_change import PendingTripChange
from hotel_assistance.domain.models.search_state import SearchState
from hotel_assistance.domain.services.filter_registry import FilterRegistry
from hotel_assistance.domain.services.relaxation import RelaxationSuggestion
from hotel_assistance.domain.services.search_validator import ValidationIssue

DEFAULT_SESSION_ID = "default"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str = Field(default=DEFAULT_SESSION_ID, min_length=1, max_length=128)


class AppliedFilterView(BaseModel):
    """One active filter, rendered for display."""

    filter_id: str
    label: str
    value_label: str
    strength: str
    type: str


class PendingChangeView(BaseModel):
    """A trip detail the user replaced but has not pinned down yet.

    Shown so the panel can say why a detail went blank, rather than leaving
    the user to guess. The value it superseded stays server-side: it is there
    to be restored, not to be displayed as if it were still in the search.
    """

    field: str
    hint: str


class SearchStateView(BaseModel):
    destination: str | None = None
    check_in: date | None = None
    check_out: date | None = None
    adults: int | None = None
    children: int | None = None
    filters: list[AppliedFilterView] = []
    pending: PendingChangeView | None = None
    ready_for_search: bool = False


class ChatResponse(BaseModel):
    reply: str
    state: SearchStateView
    issues: list[ValidationIssue] = []
    unmapped_requests: list[str] = []
    missing_trip_info: list[str] = []
    candidate_filter_ids: list[str] = []
    available_offers_count: int | None = None
    backend_available: bool = False
    relaxation_suggestions: list[RelaxationSuggestion] = []


def to_state_view(
    state: SearchState,
    registry: FilterRegistry,
    pending: PendingTripChange | None = None,
) -> SearchStateView:
    filters: list[AppliedFilterView] = []
    for applied in state.filters:
        definition = registry.get(applied.filter_id)
        if definition is None:
            continue
        is_range = isinstance(applied.value, RangeValue)
        filters.append(
            AppliedFilterView(
                filter_id=applied.filter_id,
                label=definition.description,
                value_label=applied.value.describe(definition.unit) if is_range else ("yes" if applied.value else "no"),
                strength=applied.strength.value,
                type=definition.type.value,
            )
        )

    return SearchStateView(
        destination=state.destination,
        check_in=state.check_in,
        check_out=state.check_out,
        adults=state.guests.adults if state.guests else None,
        children=state.guests.children if state.guests else None,
        filters=filters,
        pending=PendingChangeView(field=pending.field.value, hint=pending.hint) if pending else None,
        ready_for_search=state.is_ready_for_search(),
    )


def to_chat_response(result: ChatResult, registry: FilterRegistry) -> ChatResponse:
    return ChatResponse(
        reply=result.reply,
        state=to_state_view(result.state, registry, result.pending),
        issues=result.issues,
        unmapped_requests=result.unmapped_requests,
        missing_trip_info=result.missing_trip_info,
        candidate_filter_ids=[candidate.definition.id for candidate in result.candidates],
        available_offers_count=result.available_offers_count,
        backend_available=result.backend_available,
        relaxation_suggestions=result.relaxation_suggestions,
    )
