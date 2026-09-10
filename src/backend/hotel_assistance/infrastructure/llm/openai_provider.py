import json
import logging
import time
from typing import Any

from hotel_assistance.domain.models.extraction import ExtractionResult
from hotel_assistance.domain.models.filter_definition import FilterType
from hotel_assistance.domain.models.filter_value import RangeValue
from hotel_assistance.domain.models.pending_change import PendingTripChange
from hotel_assistance.domain.models.search_state import SearchState
from hotel_assistance.infrastructure.llm.prompts import EXTRACTION_INSTRUCTIONS
from hotel_assistance.infrastructure.llm.provider import (
    ExtractionRequest,
    LLMExtractionError,
)

logger = logging.getLogger(__name__)

# Reasoning-family models (gpt-5, o-series) reject an explicit `temperature`.
REASONING_MODEL_PREFIXES = ("gpt-5", "o1", "o3", "o4")


class OpenAIProvider:
    """LLMProvider backed by the OpenAI Responses API with Structured Outputs.

    All OpenAI SDK imports and request construction stay inside this adapter;
    the rest of the application only sees ExtractionRequest/ExtractionResult.
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        fallback_model: str | None = None,
        fallback_max_words: int = 12,
        temperature: float | None = None,
        client: Any | None = None,
    ) -> None:
        if client is None:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=api_key) if api_key else AsyncOpenAI()

        self._client = client
        self._model = model
        self._fallback_model = fallback_model
        self._fallback_max_words = fallback_max_words
        self._temperature = temperature

    async def extract(self, request: ExtractionRequest) -> ExtractionResult:
        model = self._select_model(request)
        request_kwargs: dict[str, Any] = {
            "model": model,
            "instructions": EXTRACTION_INSTRUCTIONS,
            "input": _build_input(request),
            # text_format triggers Structured Outputs: the SDK derives a strict
            # JSON schema from ExtractionResult and parses the reply back into it.
            "text_format": ExtractionResult,
        }
        if self._temperature is not None and not model.startswith(REASONING_MODEL_PREFIXES):
            request_kwargs["temperature"] = self._temperature

        started = time.perf_counter()
        try:
            response = await self._client.responses.parse(**request_kwargs)
        except Exception as exc:  # noqa: BLE001 - SDK errors must not leak outward
            raise LLMExtractionError(f"OpenAI extraction request failed: {exc}") from exc

        elapsed_ms = (time.perf_counter() - started) * 1000
        usage = getattr(response, "usage", None)
        logger.info(
            "llm extraction: model=%s elapsed_ms=%.1f candidates=%d input_tokens=%s output_tokens=%s",
            model,
            elapsed_ms,
            len(request.candidates),
            getattr(usage, "input_tokens", None),
            getattr(usage, "output_tokens", None),
        )

        result = getattr(response, "output_parsed", None)
        if result is None:
            refusal = getattr(response, "refusal", None)
            raise LLMExtractionError(
                f"OpenAI returned no structured extraction result ({refusal})"
                if refusal
                else "OpenAI returned no structured extraction result"
            )
        return result

    def _select_model(self, request: ExtractionRequest) -> str:
        """Route short opening messages to the cheaper model.

        Long, detail-dense first messages are where the stronger model earns
        its cost; a handful of words does not need it. A later turn is the
        exception: "I need something in May" is short but only means anything
        against CURRENT_STATE, and reading that context correctly is exactly
        what the weaker model gets wrong.
        """

        if not self._fallback_model or request.history:
            return self._model
        if len(request.message.split()) <= self._fallback_max_words:
            logger.debug("model routing: fallback=%s", self._fallback_model)
            return self._fallback_model
        return self._model


def _build_input(request: ExtractionRequest) -> str:
    candidates = [
        {
            "id": candidate.definition.id,
            "type": candidate.definition.type.value,
            "description": candidate.definition.description,
            "aliases": candidate.definition.aliases,
            "unit": candidate.definition.unit,
        }
        for candidate in request.candidates
    ]
    sections = [
        f"TODAY: {request.today.isoformat()}",
        f"CURRENT_STATE:\n{json.dumps(_state_summary(request.state), ensure_ascii=False, indent=2)}",
        f"CANDIDATE_FILTERS:\n{json.dumps(candidates, ensure_ascii=False, indent=2)}",
    ]
    if request.pending is not None:
        sections.append(
            f"PENDING_CHANGE:\n{json.dumps(_pending_summary(request.pending), ensure_ascii=False, indent=2)}"
        )
    if request.history:
        transcript = "\n".join(f"{turn.role.value}: {turn.content}" for turn in request.history)
        sections.append(f"CONVERSATION_SO_FAR:\n{transcript}")
    sections.append(f"USER_MESSAGE:\n{request.message}")
    return "\n\n".join(sections)


def _pending_summary(pending: PendingTripChange) -> dict[str, Any]:
    """The open trip question, with the value it replaced still recoverable."""

    return {
        "field": pending.field.value,
        "user_words": pending.hint,
        "superseded_value": {
            "destination": pending.previous_destination,
            "check_in": pending.previous_check_in.isoformat() if pending.previous_check_in else None,
            "check_out": pending.previous_check_out.isoformat() if pending.previous_check_out else None,
        },
    }


def _state_summary(state: SearchState) -> dict[str, Any]:
    """Render the validated state in the same vocabulary as the output schema."""

    return {
        "destination": state.destination,
        "check_in": state.check_in.isoformat() if state.check_in else None,
        "check_out": state.check_out.isoformat() if state.check_out else None,
        "guests": state.guests.model_dump() if state.guests else None,
        "filters": [
            {
                "filter_id": applied.filter_id,
                "type": FilterType.RANGE.value
                if isinstance(applied.value, RangeValue)
                else FilterType.BOOLEAN.value,
                "value": applied.value.model_dump() if isinstance(applied.value, RangeValue) else applied.value,
                "strength": applied.strength.value,
            }
            for applied in state.filters
        ],
    }
