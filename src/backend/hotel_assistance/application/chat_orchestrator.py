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

from hotel_assistance.application.patch_builder import build_patch
from hotel_assistance.application.reply_composer import (
    OUT_OF_SCOPE_REPLY,
    compose_reply,
)
from hotel_assistance.application.session_store import SessionStore
from hotel_assistance.domain.models.candidate_filter import CandidateFilter
from hotel_assistance.domain.models.chat import ChatRole
from hotel_assistance.domain.models.search_state import SearchState
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
    OfferCount,
)
from hotel_assistance.infrastructure.llm.provider import (
    ExtractionRequest,
    LLMExtractionError,
    LLMProvider,
)

logger = logging.getLogger(__name__)

StageCallback = Callable[["ChatStage"], Awaitable[None]]


class ChatStage(StrEnum):
    """Progress markers a caller can surface while a turn is being processed."""

    RETRIEVING = "retrieving_candidates"
    EXTRACTING = "extracting_intent"
    VALIDATING = "validating"
    SEARCHING = "searching_offers"
    DONE = "done"


class ChatResult(BaseModel):
    reply: str
    state: SearchState
    issues: list[ValidationIssue] = Field(default_factory=list)
    unmapped_requests: list[str] = Field(default_factory=list)
    missing_trip_info: list[str] = Field(default_factory=list)
    candidates: list[CandidateFilter] = Field(default_factory=list)
    available_offers_count: int | None = None
    backend_available: bool = False
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

    def reset(self, session_id: str) -> SearchState:
        return self._sessions.reset(session_id).state

    async def handle_message(
        self,
        session_id: str,
        message: str,
        on_stage: StageCallback | None = None,
    ) -> ChatResult:
        session = self._sessions.get(session_id)

        await _notify(on_stage, ChatStage.RETRIEVING)
        candidates = await self._retriever.retrieve(query=message, top_k=self._top_k)

        await _notify(on_stage, ChatStage.EXTRACTING)
        request = ExtractionRequest(
            message=message,
            candidates=candidates,
            state=session.state,
            history=list(session.history),
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
            session.record(ChatRole.ASSISTANT, OUT_OF_SCOPE_REPLY)
            await _notify(on_stage, ChatStage.DONE)
            return ChatResult(reply=OUT_OF_SCOPE_REPLY, state=session.state, candidates=candidates)

        await _notify(on_stage, ChatStage.VALIDATING)
        patch, build_issues = build_patch(extraction, candidates, self._registry, session.state)
        outcome = self._validator.apply(session.state, patch)
        session.state = outcome.state
        issues = build_issues + outcome.issues

        await _notify(on_stage, ChatStage.SEARCHING)
        offers = await self._count_offers(session.state)
        relaxations: list[RelaxationSuggestion] = []
        if offers.available_offers_count == 0:
            relaxations = suggest_relaxations(session.state, self._registry)

        reply = compose_reply(
            state=session.state,
            registry=self._registry,
            applied=outcome.applied,
            issues=issues,
            unmapped_requests=extraction.unmapped_requests,
            missing_trip_info=list(extraction.missing_trip_info),
            clarification_question=extraction.clarification_question,
            available_offers_count=offers.available_offers_count,
            relaxations=relaxations,
            was_reset=patch.reset,
        )
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
            state=session.state,
            issues=issues,
            unmapped_requests=extraction.unmapped_requests,
            missing_trip_info=list(extraction.missing_trip_info),
            candidates=candidates,
            available_offers_count=offers.available_offers_count,
            backend_available=offers.backend_available,
            relaxation_suggestions=relaxations,
        )

    async def _count_offers(self, state: SearchState) -> OfferCount:
        if not state.is_ready_for_search():
            return OfferCount()
        try:
            return await self._hotel_search_client.count_offers(state)
        except HotelSearchError as exc:
            # A backend outage must not fabricate a count, and must not lose
            # the filter work the user just did.
            logger.warning("hotel backend unavailable: %s", exc)
            return OfferCount()


async def _notify(on_stage: StageCallback | None, stage: ChatStage) -> None:
    if on_stage is not None:
        await on_stage(stage)
