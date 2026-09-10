from datetime import date
from typing import Protocol

from pydantic import BaseModel, Field

from hotel_assistance.domain.models.candidate_filter import CandidateFilter
from hotel_assistance.domain.models.chat import ChatTurn
from hotel_assistance.domain.models.extraction import ExtractionResult
from hotel_assistance.domain.models.pending_change import PendingTripChange
from hotel_assistance.domain.models.search_state import SearchState


class LLMExtractionError(Exception):
    """Raised when a provider cannot produce a valid ExtractionResult.

    Adapters must translate provider-specific failures (SDK exceptions,
    malformed responses, network errors) into this application-level error.
    """


class ExtractionRequest(BaseModel):
    """Everything a provider needs to interpret one user message.

    Application-level and provider-agnostic: no adapter may require anything
    beyond this, and nothing here is provider-specific.
    """

    message: str
    candidates: list[CandidateFilter] = Field(default_factory=list)
    state: SearchState = Field(default_factory=SearchState)
    history: list[ChatTurn] = Field(default_factory=list)
    pending: PendingTripChange | None = None
    today: date


class LLMProvider(Protocol):
    """Provider-independent interface for extracting structured search intent.

    Implementations must not own search-state mutation, filter conflict
    rules, date/range validation, availability, or offer counts; they only
    translate natural language into an ExtractionResult.
    """

    async def extract(self, request: ExtractionRequest) -> ExtractionResult:
        """Extract structured intent from a user message.

        Raises:
            LLMExtractionError: if the provider fails or returns output that
                cannot be parsed into an ExtractionResult.
        """
        ...
