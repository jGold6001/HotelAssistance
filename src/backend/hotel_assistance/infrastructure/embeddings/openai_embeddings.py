import logging
from typing import Any

from hotel_assistance.infrastructure.embeddings.provider import EmbeddingError

logger = logging.getLogger(__name__)

# The embeddings endpoint accepts large batches, but a bounded chunk keeps a
# full-registry rebuild well inside request size limits.
BATCH_SIZE = 256


class OpenAIEmbeddingProvider:
    """EmbeddingProvider backed by the OpenAI embeddings API."""

    def __init__(self, model: str, api_key: str | None = None, client: Any | None = None) -> None:
        if client is None:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=api_key) if api_key else AsyncOpenAI()

        self._client = client
        self._model = model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            batch = texts[start : start + BATCH_SIZE]
            try:
                response = await self._client.embeddings.create(model=self._model, input=batch)
            except Exception as exc:  # noqa: BLE001 - SDK errors must not leak outward
                raise EmbeddingError(f"OpenAI embedding request failed: {exc}") from exc
            vectors.extend(item.embedding for item in response.data)

        if len(vectors) != len(texts):
            raise EmbeddingError(f"Expected {len(texts)} embeddings, received {len(vectors)}")
        return vectors
