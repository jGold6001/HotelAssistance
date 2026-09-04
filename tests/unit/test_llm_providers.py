import asyncio

import pytest

from hotel_assistance.infrastructure.llm.ollama_provider import OllamaProvider
from hotel_assistance.infrastructure.llm.openai_provider import OpenAIProvider
from hotel_assistance.infrastructure.llm.provider import LLMExtractionError


def test_openai_provider_placeholder_raises_extraction_error() -> None:
    provider = OpenAIProvider(api_key="test-key", model="gpt-4o-mini")

    with pytest.raises(LLMExtractionError):
        asyncio.run(provider.extract_search_patch("Find me a hotel in Paris"))


def test_ollama_provider_placeholder_raises_extraction_error() -> None:
    provider = OllamaProvider(base_url="http://localhost:11434", model="llama3.1")

    with pytest.raises(LLMExtractionError):
        asyncio.run(provider.extract_search_patch("Find me a hotel in Paris"))
