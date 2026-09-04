from hotel_assistance.domain.models.search_patch import SearchPatch
from hotel_assistance.infrastructure.llm.provider import LLMExtractionError


class OllamaProvider:
    """LLMProvider backed by a local Ollama instance.

    Placeholder: real request/response handling is not implemented yet.
    Output must be validated against the same Pydantic models and domain
    rules used by OpenAIProvider; no separate validation flow.
    """

    def __init__(self, base_url: str, model: str) -> None:
        self._base_url = base_url
        self._model = model

    async def extract_search_patch(
        self,
        message: str,
        conversation_history: list[str] | None = None,
    ) -> SearchPatch:
        raise LLMExtractionError("OllamaProvider is not implemented yet")
