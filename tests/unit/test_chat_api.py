import json

import pytest
from fastapi.testclient import TestClient
from hotel_assistance.api.dependencies import get_orchestrator, get_registry
from hotel_assistance.application.chat_orchestrator import ChatResult, ChatStage
from hotel_assistance.domain.models.applied_filter import AppliedFilter
from hotel_assistance.domain.models.filter_definition import FilterDefinition
from hotel_assistance.domain.models.filter_value import RangeValue
from hotel_assistance.domain.models.search_state import SearchState
from hotel_assistance.domain.services.filter_registry import FilterRegistry
from hotel_assistance.infrastructure.llm.provider import LLMExtractionError
from hotel_assistance.main import app

REGISTRY = FilterRegistry(
    [
        FilterDefinition(id="hotel.parking", type="boolean", description="Parking"),
        FilterDefinition(id="room.size_m2", type="range", description="Room floor area", unit="m2"),
    ]
)

STATE = SearchState(
    destination="Haarlem",
    filters=[
        AppliedFilter(filter_id="hotel.parking", value=True),
        AppliedFilter(filter_id="room.size_m2", value=RangeValue(min=30), strength="preferred"),
    ],
)


class FakeOrchestrator:
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error
        self.state = STATE

    async def handle_message(self, session_id: str, message: str, on_stage=None) -> ChatResult:
        if self._error is not None:
            raise self._error
        if on_stage is not None:
            for stage in ChatStage:
                await on_stage(stage)
        return ChatResult(reply=f"Applied: Parking. ({message})", state=self.state)

    def state_for(self, session_id: str) -> SearchState:
        return self.state

    def reset(self, session_id: str) -> SearchState:
        self.state = SearchState()
        return self.state


@pytest.fixture
def client():
    def override(orchestrator: FakeOrchestrator):
        app.dependency_overrides[get_orchestrator] = lambda: orchestrator
        app.dependency_overrides[get_registry] = lambda: REGISTRY
        return TestClient(app)

    yield override
    app.dependency_overrides.clear()


def test_chat_returns_reply_and_rendered_state(client) -> None:
    response = client(FakeOrchestrator()).post("/api/chat", json={"message": "I need parking"})

    assert response.status_code == 200
    body = response.json()
    assert "Applied: Parking." in body["reply"]
    assert body["state"]["destination"] == "Haarlem"
    assert body["state"]["filters"] == [
        {
            "filter_id": "hotel.parking",
            "label": "Parking",
            "value_label": "yes",
            "strength": "required",
            "type": "boolean",
        },
        {
            "filter_id": "room.size_m2",
            "label": "Room floor area",
            "value_label": "at least 30 m2",
            "strength": "preferred",
            "type": "range",
        },
    ]


def test_empty_message_is_rejected(client) -> None:
    assert client(FakeOrchestrator()).post("/api/chat", json={"message": ""}).status_code == 422


def test_extraction_failure_becomes_a_bad_gateway(client) -> None:
    response = client(FakeOrchestrator(error=LLMExtractionError("model unavailable"))).post(
        "/api/chat", json={"message": "I need parking"}
    )

    assert response.status_code == 502


def test_stream_emits_stages_before_the_result(client) -> None:
    with client(FakeOrchestrator()).stream(
        "POST", "/api/chat/stream", json={"message": "I need parking"}
    ) as response:
        assert response.status_code == 200
        events = [json.loads(line) for line in response.iter_lines() if line.strip()]

    assert [event["stage"] for event in events[:-1]] == [stage.value for stage in ChatStage]
    assert events[-1]["type"] == "result"
    assert "Applied: Parking." in events[-1]["reply"]


def test_stream_reports_failures_as_an_error_event(client) -> None:
    with client(FakeOrchestrator(error=LLMExtractionError("model unavailable"))).stream(
        "POST", "/api/chat/stream", json={"message": "I need parking"}
    ) as response:
        events = [json.loads(line) for line in response.iter_lines() if line.strip()]

    assert events == [{"type": "error", "message": "model unavailable"}]


def test_state_can_be_read_and_reset(client) -> None:
    test_client = client(FakeOrchestrator())

    assert test_client.get("/api/state").json()["destination"] == "Haarlem"
    assert test_client.post("/api/state/reset").json()["filters"] == []


def test_frontend_is_served_at_the_root(client) -> None:
    response = client(FakeOrchestrator()).get("/")

    assert response.status_code == 200
    assert "Hotel Assistance" in response.text
