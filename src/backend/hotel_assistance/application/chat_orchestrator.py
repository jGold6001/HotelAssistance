"""Coordinates one chat turn end to end.

Order of responsibility: retrieval narrows the registry, the LLM interprets
language, and everything after that is deterministic. The orchestrator itself
owns no business rules - it delegates them to the domain services.
"""

import logging
from collections.abc import Awaitable, Callable
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field, ValidationError

from hotel_assistance.application.patch_builder import build_patch, clean_unmapped_requests
from hotel_assistance.application.reply_composer import (
    NOTHING_CHANGED,
    compose_filters_reply,
    compose_offers_reply,
    compose_out_of_scope_reply,
    compose_simulated_search_reply,
    join_replies,
)
from hotel_assistance.application.session_store import Session, SessionStore
from hotel_assistance.application.simulator_directive import extract_offer_directive
from hotel_assistance.domain.models.candidate_filter import CandidateFilter
from hotel_assistance.domain.models.chat import ChatRole
from hotel_assistance.domain.models.extraction import TripDetails
from hotel_assistance.domain.models.hotel_offer import HotelOffer
from hotel_assistance.domain.models.pending_change import PendingTripChange
from hotel_assistance.domain.models.search_state import SearchState
from hotel_assistance.domain.models.trip_field import TripField
from hotel_assistance.domain.services.candidate_retriever import CandidateRetriever
from hotel_assistance.domain.services.filter_registry import FilterRegistry
from hotel_assistance.domain.services.relaxation import (
    RelaxationSuggestion,
    suggest_relaxations,
)
from hotel_assistance.domain.services.search_validator import (
    SearchValidator,
    ValidationIssue,
)
from hotel_assistance.infrastructure.hotel_search.client import (
    HotelSearchClient,
    HotelSearchError,
    OfferResult,
)
from hotel_assistance.infrastructure.llm.provider import (
    ExtractionRequest,
    LLMExtractionError,
    LLMProvider,
)

logger = logging.getLogger(__name__)

StageCallback = Callable[["ChatStage"], Awaitable[None]]
PartialCallback = Callable[["ChatResult"], Awaitable[None]]


class ChatStage(StrEnum):
    """Progress markers a caller can surface while a turn is being processed."""

    RETRIEVING = "retrieving_candidates"
    EXTRACTING = "extracting_intent"
    VALIDATING = "validating"
    SEARCHING = "searching_offers"
    DONE = "done"


class ChatResult(BaseModel):
    reply: str
    # The two halves the reply is made of: what validation settled, and what
    # the hotel backend answered afterwards. A streaming caller shows them as
    # they arrive; anyone else reads ``reply``.
    filters_reply: str = ""
    offers_reply: str = ""
    state: SearchState
    pending: PendingTripChange | None = None
    issues: list[ValidationIssue] = Field(default_factory=list)
    unmapped_requests: list[str] = Field(default_factory=list)
    missing_trip_info: list[str] = Field(default_factory=list)
    candidates: list[CandidateFilter] = Field(default_factory=list)
    available_offers_count: int | None = None
    backend_available: bool = False
    offers: list[HotelOffer] = Field(default_factory=list)
    relaxation_suggestions: list[RelaxationSuggestion] = Field(default_factory=list)


class ChatOrchestrator:
    def __init__(
        self,
        registry: FilterRegistry,
        retriever: CandidateRetriever,
        llm_provider: LLMProvider,
        validator: SearchValidator,
        hotel_search_client: HotelSearchClient,
        sessions: SessionStore,
        top_k: int = 24,
    ) -> None:
        self._registry = registry
        self._retriever = retriever
        self._llm_provider = llm_provider
        self._validator = validator
        self._hotel_search_client = hotel_search_client
        self._sessions = sessions
        self._top_k = top_k

    def state_for(self, session_id: str) -> SearchState:
        return self._sessions.get(session_id).state

    def pending_for(self, session_id: str) -> PendingTripChange | None:
        return self._sessions.get(session_id).pending

    def reset(self, session_id: str) -> SearchState:
        return self._sessions.reset(session_id).state

    async def handle_message(
        self,
        session_id: str,
        message: str,
        on_stage: StageCallback | None = None,
        on_partial: PartialCallback | None = None,
    ) -> ChatResult:
        session = self._sessions.get(session_id)

        # The test directive is an instruction to the simulated backend, not
        # something to interpret as a search request, so it leaves the message
        # before retrieval and extraction ever see it.
        message, requested_offers = extract_offer_directive(message)
        if requested_offers is not None and not message:
            return await self._handle_directive_only(session, requested_offers, on_stage)

        await _notify(on_stage, ChatStage.RETRIEVING)
        candidates = await self._retriever.retrieve(query=message, top_k=self._top_k)

        await _notify(on_stage, ChatStage.EXTRACTING)
        request = ExtractionRequest(
            message=message,
            candidates=candidates,
            state=session.state,
            history=list(session.history),
            pending=session.pending,
            today=date.today(),
        )
        try:
            extraction = await self._llm_provider.extract(request)
        except ValidationError as exc:
            # Structured output that does not satisfy the contract is a hard
            # failure: guessing what the model meant would defeat the schema.
            raise LLMExtractionError(f"Model returned output that failed validation: {exc}") from exc

        session.record(ChatRole.USER, message)

        if not extraction.is_hotel_search_related:
            # A refusal must not cost the user the search they already built.
            reply = compose_out_of_scope_reply(session.state)
            session.record(ChatRole.ASSISTANT, reply)
            await _notify(on_stage, ChatStage.DONE)
            return ChatResult(
                reply=reply,
                filters_reply=reply,
                state=session.state,
                pending=session.pending,
                missing_trip_info=session.state.missing_trip_info(),
                candidates=candidates,
            )

        await _notify(on_stage, ChatStage.VALIDATING)
        patch, build_issues = build_patch(extraction, candidates, self._registry, session.state)
        previous_state = session.state
        outcome = self._validator.apply(session.state, patch)
        session.state = outcome.state
        issues = build_issues + outcome.issues
        unmapped_requests = clean_unmapped_requests(extraction)

        # A vague change opens a question; the state answering it closes one.
        carried = None if patch.reset else _resolve_pending(session.pending, session.state)
        session.pending = _open_pending(extraction.trip, previous_state, session.state) or carried

        # Everything the filters half says is settled by now, so it goes out
        # before the backend is asked anything - the user reads what the
        # search became while the search itself is still running.
        filters_reply = compose_filters_reply(
            state=session.state,
            registry=self._registry,
            applied=outcome.applied,
            applied_trip=outcome.applied_trip,
            issues=issues,
            unmapped_requests=unmapped_requests,
            clarification_question=extraction.clarification_question,
            was_reset=patch.reset,
            destination_hint=_hint_for(TripField.DESTINATION, extraction.trip.destination_hint, session.pending),
            date_hint=_hint_for(TripField.DATES, extraction.trip.date_hint, session.pending),
        )
        if filters_reply.text and on_partial is not None:
            await on_partial(
                ChatResult(
                    reply=filters_reply.text,
                    filters_reply=filters_reply.text,
                    state=session.state,
                    pending=session.pending,
                    issues=issues,
                    unmapped_requests=unmapped_requests,
                    missing_trip_info=session.state.missing_trip_info(),
                    candidates=candidates,
                )
            )

        await _notify(on_stage, ChatStage.SEARCHING)
        offers = await self._search_offers(session.state, requested_offers)
        relaxations: list[RelaxationSuggestion] = []
        if offers.available_offers_count == 0:
            relaxations = suggest_relaxations(session.state, self._registry)

        offers_reply = compose_offers_reply(
            state=session.state,
            registry=self._registry,
            available_offers_count=offers.available_offers_count,
            relaxations=relaxations,
            offers_note=offers.note,
            # The filters half already named the trip, so the count does not.
            include_trip=not filters_reply.named_trip,
        )
        # A turn that settled nothing and reached no backend still has to say
        # something, and by then the second message is the only one left.
        if not filters_reply.text and not offers_reply:
            offers_reply = NOTHING_CHANGED
        reply = join_replies(filters_reply.text, offers_reply)
        session.record(ChatRole.ASSISTANT, reply)

        logger.info(
            "chat turn: session=%s candidates=%d applied=%d issues=%d offers=%s",
            session_id,
            len(candidates),
            len(outcome.applied),
            len(issues),
            offers.available_offers_count,
        )
        await _notify(on_stage, ChatStage.DONE)

        return ChatResult(
            reply=reply,
            filters_reply=filters_reply.text,
            offers_reply=offers_reply,
            state=session.state,
            pending=session.pending,
            issues=issues,
            unmapped_requests=unmapped_requests,
            # What is still missing is a fact about the validated state, not
            # something the model is asked to keep track of.
            missing_trip_info=session.state.missing_trip_info(),
            candidates=candidates,
            available_offers_count=offers.available_offers_count,
            backend_available=offers.backend_available,
            offers=offers.offers,
            relaxation_suggestions=relaxations,
        )

    async def _handle_directive_only(
        self,
        session: Session,
        requested_offers: int | None,
        on_stage: StageCallback | None,
    ) -> ChatResult:
        """Answer a message that was nothing but a ``@test_aparts`` directive.

        There is no language to interpret, so retrieval and the model are
        skipped entirely: the turn only re-runs the simulated search and
        leaves the state exactly as it was.
        """

        await _notify(on_stage, ChatStage.SEARCHING)
        offers = await self._search_offers(session.state, requested_offers)
        relaxations: list[RelaxationSuggestion] = []
        if offers.available_offers_count == 0:
            relaxations = suggest_relaxations(session.state, self._registry)

        reply = compose_simulated_search_reply(
            session.state, self._registry, offers.available_offers_count, relaxations, offers.note
        )
        await _notify(on_stage, ChatStage.DONE)
        return ChatResult(
            reply=reply,
            offers_reply=reply,
            state=session.state,
            pending=session.pending,
            missing_trip_info=session.state.missing_trip_info(),
            available_offers_count=offers.available_offers_count,
            backend_available=offers.backend_available,
            offers=offers.offers,
            relaxation_suggestions=relaxations,
        )

    async def _search_offers(self, state: SearchState, requested_offers: int | None) -> OfferResult:
        # A test directive is an explicit instruction to query the simulated
        # backend, so it overrides the usual "only search once the trip is
        # fully specified" gate.
        if requested_offers is None and not state.is_ready_for_search():
            return OfferResult()
        try:
            return await self._hotel_search_client.search_offers(state, requested_offers)
        except HotelSearchError as exc:
            # A backend outage must not fabricate a count, and must not lose
            # the filter work the user just did.
            logger.warning("hotel backend unavailable: %s", exc)
            return OfferResult()


def _open_pending(
    trip: TripDetails,
    previous: SearchState,
    current: SearchState,
) -> PendingTripChange | None:
    """Remember the value a vague change dropped, while the question is open.

    Only worth recording while the detail is still unknown: once the state has
    a real value again there is nothing left to ask or to restore.
    """

    if trip.date_hint and current.date_range() is None:
        return PendingTripChange(
            field=TripField.DATES,
            hint=trip.date_hint,
            previous_check_in=previous.check_in,
            previous_check_out=previous.check_out,
        )
    if trip.destination_hint and not current.destination:
        return PendingTripChange(
            field=TripField.DESTINATION,
            hint=trip.destination_hint,
            previous_destination=previous.destination,
        )
    return None


def _resolve_pending(pending: PendingTripChange | None, state: SearchState) -> PendingTripChange | None:
    """Drop a remembered change once the state answers it."""

    if pending is None:
        return None
    if pending.field is TripField.DATES and state.date_range() is not None:
        return None
    if pending.field is TripField.DESTINATION and state.destination:
        return None
    return pending


def _hint_for(field: TripField, hint: str | None, pending: PendingTripChange | None) -> str | None:
    """Keep echoing the user's own words while their question stays open."""

    if hint:
        return hint
    return pending.hint if pending is not None and pending.field is field else None


async def _notify(on_stage: StageCallback | None, stage: ChatStage) -> None:
    if on_stage is not None:
        await on_stage(stage)
