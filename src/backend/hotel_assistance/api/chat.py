import asyncio
import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from hotel_assistance.api.dependencies import get_orchestrator, get_registry
from hotel_assistance.api.schemas import (
    DEFAULT_SESSION_ID,
    ChatRequest,
    ChatResponse,
    SearchStateView,
    to_chat_response,
    to_state_view,
)
from hotel_assistance.application.chat_orchestrator import ChatOrchestrator, ChatStage
from hotel_assistance.domain.services.filter_registry import FilterRegistry
from hotel_assistance.infrastructure.llm.provider import LLMExtractionError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    orchestrator: ChatOrchestrator = Depends(get_orchestrator),
    registry: FilterRegistry = Depends(get_registry),
) -> ChatResponse:
    try:
        result = await orchestrator.handle_message(request.session_id, request.message)
    except LLMExtractionError as exc:
        logger.warning("extraction failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return to_chat_response(result, registry)


@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    orchestrator: ChatOrchestrator = Depends(get_orchestrator),
    registry: FilterRegistry = Depends(get_registry),
) -> StreamingResponse:
    """Stream real processing stages, then the final result, as NDJSON.

    Stages are emitted by the orchestrator as they actually happen, so the
    thinking indicator in the UI reflects work rather than a timer. Once the
    response has started there is no status code left to set, so failures are
    reported as an ``error`` event instead.
    """

    async def event_stream() -> AsyncIterator[str]:
        events: asyncio.Queue[str | None] = asyncio.Queue()

        async def on_stage(stage: ChatStage) -> None:
            await events.put(json.dumps({"type": "stage", "stage": stage.value}))

        async def run_turn() -> None:
            try:
                result = await orchestrator.handle_message(
                    request.session_id, request.message, on_stage=on_stage
                )
                payload = to_chat_response(result, registry).model_dump(mode="json")
                await events.put(json.dumps({"type": "result", **payload}))
            except LLMExtractionError as exc:
                logger.warning("extraction failed: %s", exc)
                await events.put(json.dumps({"type": "error", "message": str(exc)}))
            except Exception:
                logger.exception("chat turn failed")
                await events.put(
                    json.dumps({"type": "error", "message": "The assistant failed to process this message."})
                )
            finally:
                await events.put(None)

        task = asyncio.create_task(run_turn())
        try:
            while True:
                event = await events.get()
                if event is None:
                    break
                yield event + "\n"
        finally:
            # A client that disconnects mid-turn must not leave the turn running.
            task.cancel()

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@router.get("/state", response_model=SearchStateView)
async def read_state(
    session_id: str = DEFAULT_SESSION_ID,
    orchestrator: ChatOrchestrator = Depends(get_orchestrator),
    registry: FilterRegistry = Depends(get_registry),
) -> SearchStateView:
    return to_state_view(orchestrator.state_for(session_id), registry)


@router.post("/state/reset", response_model=SearchStateView)
async def reset_state(
    session_id: str = DEFAULT_SESSION_ID,
    orchestrator: ChatOrchestrator = Depends(get_orchestrator),
    registry: FilterRegistry = Depends(get_registry),
) -> SearchStateView:
    return to_state_view(orchestrator.reset(session_id), registry)
