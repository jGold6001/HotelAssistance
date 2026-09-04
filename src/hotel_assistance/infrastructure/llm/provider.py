from typing import Protocol

from hotel_assistance.domain.models.search_patch import SearchPatch


class LLMExtractionError(Exception):
    """Raised when a provider cannot produce a valid SearchPatch.

    Adapters must translate provider-specific failures (SDK exceptions,
    malformed responses, network errors) into this application-level error.
    """


class LLMProvider(Protocol):
    """Provider-independent interface for extracting structured search intent.

    Implementations must not own search-state mutation, filter conflict
    rules, date/range validation, or any other domain business rule; they
    only translate natural language into a SearchPatch.
    """

    async def extract_search_patch(
        self,
        message: str,
        conversation_history: list[str] | None = None,
    ) -> SearchPatch:
        """Extract a SearchPatch from a user message.

        Raises:
            LLMExtractionError: if the provider fails or returns output that
                cannot be normalized into a SearchPatch.
        """
        ...
