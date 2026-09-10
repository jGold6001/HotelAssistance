import asyncio
import json
from datetime import date

import pytest
from hotel_assistance.domain.models.candidate_filter import CandidateFilter
from hotel_assistance.domain.models.extraction import ExtractionResult
from hotel_assistance.domain.models.filter_definition import FilterDefinition
from hotel_assistance.infrastructure.llm.openai_provider import OpenAIProvider
from hotel_assistance.infrastructure.llm.provider import (
    ExtractionRequest,
    LLMExtractionError,
)


class FakeResponses:
    def __init__(self, parsed: ExtractionResult | None = None, error: Exception | None = None) -> None:
        self.parsed = parsed
        self.error = error
        self.calls: list[dict] = []

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return type("Response", (), {"output_parsed": self.parsed, "usage": None, "refusal": None})()


class FakeClient:
    def __init__(self, responses: FakeResponses) -> None:
        self.responses = responses


def build_request(message: str = "I would like a quiet hotel with parking") -> ExtractionRequest:
    return ExtractionRequest(
        message=message,
        candidates=[
            CandidateFilter(
                definition=FilterDefinition(id="hotel.parking", type="boolean", description="Parking"),
                score=0.9,
            )
        ],
        today=date(2026, 9, 9),
    )


def build_provider(responses: FakeResponses, **kwargs) -> OpenAIProvider:
    return OpenAIProvider(model="gpt-5-mini", client=FakeClient(responses), **kwargs)


def test_structured_output_is_returned_unchanged() -> None:
    expected = ExtractionResult(unmapped_requests=["a hot tub on the roof"])
    responses = FakeResponses(parsed=expected)

    result = asyncio.run(build_provider(responses).extract(build_request()))

    assert result == expected
    assert responses.calls[0]["text_format"] is ExtractionResult


def test_prompt_carries_candidates_today_and_message() -> None:
    responses = FakeResponses(parsed=ExtractionResult())

    asyncio.run(build_provider(responses).extract(build_request()))

    payload = responses.calls[0]["input"]
    assert "hotel.parking" in payload
    assert "2026-09-09" in payload
    assert "I would like a quiet hotel with parking" in payload


def test_backend_provenance_is_never_sent_to_the_model() -> None:
    responses = FakeResponses(parsed=ExtractionResult())
    request = build_request()
    request.candidates[0].definition.source = {"facility_id": 2, "facility_name": "PARKING"}

    asyncio.run(build_provider(responses).extract(request))

    assert "facility_id" not in responses.calls[0]["input"]


def test_short_follow_ups_are_routed_to_the_cheaper_model() -> None:
    responses = FakeResponses(parsed=ExtractionResult())
    provider = build_provider(responses, fallback_model="gpt-4.1-mini", fallback_max_words=12)

    asyncio.run(provider.extract(build_request("make it 4 stars")))
    asyncio.run(provider.extract(build_request(" ".join(["word"] * 40))))

    assert responses.calls[0]["model"] == "gpt-4.1-mini"
    assert responses.calls[1]["model"] == "gpt-5-mini"


def test_temperature_is_omitted_for_reasoning_models() -> None:
    responses = FakeResponses(parsed=ExtractionResult())

    asyncio.run(build_provider(responses, temperature=0.1).extract(build_request()))

    assert "temperature" not in responses.calls[0]


def test_temperature_is_sent_to_non_reasoning_models() -> None:
    responses = FakeResponses(parsed=ExtractionResult())
    provider = OpenAIProvider(model="gpt-4.1-mini", client=FakeClient(responses), temperature=0.1)

    asyncio.run(provider.extract(build_request()))

    assert responses.calls[0]["temperature"] == 0.1


def test_sdk_errors_are_translated() -> None:
    responses = FakeResponses(error=RuntimeError("connection reset"))

    with pytest.raises(LLMExtractionError, match="connection reset"):
        asyncio.run(build_provider(responses).extract(build_request()))


def test_missing_structured_output_fails_explicitly() -> None:
    responses = FakeResponses(parsed=None)

    with pytest.raises(LLMExtractionError):
        asyncio.run(build_provider(responses).extract(build_request()))


def test_current_state_is_described_in_the_prompt() -> None:
    from hotel_assistance.domain.models.applied_filter import AppliedFilter
    from hotel_assistance.domain.models.filter_value import RangeValue
    from hotel_assistance.domain.models.search_state import SearchState

    responses = FakeResponses(parsed=ExtractionResult())
    request = build_request()
    request.state = SearchState(
        destination="Haarlem",
        filters=[AppliedFilter(filter_id="room.size_m2", value=RangeValue(min=30))],
    )

    asyncio.run(build_provider(responses).extract(request))

    payload = responses.calls[0]["input"]
    state_block = payload.split("CURRENT_STATE:\n")[1].split("\n\nCANDIDATE_FILTERS")[0]
    state = json.loads(state_block)
    assert state["destination"] == "Haarlem"
    assert state["filters"][0] == {
        "filter_id": "room.size_m2",
        "type": "range",
        "value": {"min": 30.0, "max": None},
        "strength": "required",
    }
