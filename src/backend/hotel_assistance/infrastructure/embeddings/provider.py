from typing import Protocol


class EmbeddingError(Exception):
    """Raised when an embedding backend cannot produce vectors."""


class EmbeddingProvider(Protocol):
    """Turns text into vectors for semantic candidate retrieval."""

    async def embed(self, texts: list[str]) -> list[list[float]]: ...
