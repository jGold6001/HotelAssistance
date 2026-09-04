from hotel_assistance.domain.models.search_patch import SearchPatch
from hotel_assistance.infrastructure.llm.provider import LLMExtractionError


class OpenAIProvider:
    """LLMProvider backed by the OpenAI Responses API.

    Placeholder: real Structured Outputs integration is not implemented yet.
    All OpenAI SDK imports and request construction must stay inside this
    adapter; extraction rules and validation are shared with OllamaProvider.
    """

    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    async def extract_search_patch(
        self,
        message: str,
        conversation_history: list[str] | None = None,
    ) -> SearchPatch:
        raise LLMExtractionError("OpenAIProvider is not implemented yet")
