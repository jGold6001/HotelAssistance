"""Optional integration tests against the real OpenAI API.

Excluded from the default run (see the ``integration`` marker in
pyproject.toml) because they cost money. Run them with:

    uv run pytest -m integration
"""

import asyncio
from datetime import date

import pytest
from hotel_assistance.config.settings import Settings
from hotel_assistance.domain.models.candidate_filter import CandidateFilter
from hotel_assistance.domain.services.candidate_retriever import (
    KeywordCandidateRetriever,
)
from hotel_assistance.domain.services.filter_registry import FilterRegistry
from hotel_assistance.infrastructure.llm.openai_provider import OpenAIProvider
from hotel_assistance.infrastructure.llm.provider import ExtractionRequest

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def settings() -> Settings:
    config = Settings.from_env()
    if not config.has_openai_credentials():
        pytest.skip("No OpenAI credentials configured")
    return config


def retrieve(registry: FilterRegistry, message: str) -> list[CandidateFilter]:
    return asyncio.run(KeywordCandidateRetriever(registry).retrieve(message, top_k=30))


def test_extracts_filters_and_trip_details_from_a_real_message(settings: Settings) -> None:
    registry = FilterRegistry.default()
    message = (
        "Going to Haarlem 15-18 August next year, travelling solo. I want a quiet, "
        "soundproofed room of at least 30 square meters, and free parking would be great."
    )
    provider = OpenAIProvider(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        fallback_model=None,
    )

    result = asyncio.run(
        provider.extract(
            ExtractionRequest(
                message=message,
                candidates=retrieve(registry, message),
                today=date.today(),
            )
        )
    )

    assert result.is_hotel_search_related is True
    assert result.trip.destination is not None and "haarlem" in result.trip.destination.lower()
    assert all(item.filter_id in registry for item in result.filters)

    size = next((item for item in result.filters if item.filter_id == "room.size_m2"), None)
    assert size is not None and size.range_value.min == 30


def test_rejects_a_request_that_is_not_about_hotel_search(settings: Settings) -> None:
    registry = FilterRegistry.default()
    message = "Explain how a diesel engine works."
    provider = OpenAIProvider(model=settings.openai_model, api_key=settings.openai_api_key, fallback_model=None)

    result = asyncio.run(
        provider.extract(
            ExtractionRequest(
                message=message,
                candidates=retrieve(registry, message),
                today=date.today(),
            )
        )
    )

    assert result.is_hotel_search_related is False
    assert result.filters == []
