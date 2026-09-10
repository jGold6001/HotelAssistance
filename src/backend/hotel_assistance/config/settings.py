"""Environment-driven configuration.

Provider selection and credentials live here, outside domain logic. Secrets
are read from the environment and never logged or echoed back through the API.
"""

import os
from enum import StrEnum
from functools import lru_cache

from pydantic import BaseModel

ENV_PREFIX = "HOTEL_ASSISTANCE_"


class RetrievalMode(StrEnum):
    """How filter candidates are preselected before LLM extraction.

    ``HYBRID`` is the default: embeddings catch paraphrase, and a reserved
    lane of alias matches catches specific asks buried in a long message.
    ``KEYWORD`` needs no API calls at all.
    """

    HYBRID = "hybrid"
    SEMANTIC = "semantic"
    KEYWORD = "keyword"


class Settings(BaseModel):
    openai_api_key: str | None = None
    openai_model: str = "gpt-5-mini"
    openai_fallback_model: str | None = "gpt-4.1-mini"
    openai_fallback_max_words: int = 12
    openai_temperature: float | None = None
    openai_embedding_model: str = "text-embedding-3-small"

    retrieval_mode: RetrievalMode = RetrievalMode.HYBRID
    filter_top_k: int = 24
    embedding_cache_path: str = ".cache/filter_embeddings.json"

    hotel_backend_url: str | None = None
    hotel_backend_timeout: float = 10.0
    # With no real backend URL, the mock property simulator stands in for one.
    # Set to false to report offer counts as unknown instead.
    hotel_simulator_enabled: bool = True

    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            openai_api_key=_env("OPENAI_API_KEY"),
            openai_model=_env("OPENAI_MODEL", "gpt-5-mini"),
            openai_fallback_model=_env("OPENAI_FALLBACK_MODEL", "gpt-4.1-mini"),
            openai_fallback_max_words=int(_env("OPENAI_FALLBACK_MAX_WORDS", "12")),
            openai_temperature=_optional_float(_env("OPENAI_TEMPERATURE")),
            openai_embedding_model=_env("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
            retrieval_mode=RetrievalMode(_env("RETRIEVAL_MODE", RetrievalMode.HYBRID)),
            filter_top_k=int(_env("FILTER_TOP_K", "24")),
            embedding_cache_path=_env("EMBEDDING_CACHE_PATH", ".cache/filter_embeddings.json"),
            hotel_backend_url=_env("HOTEL_BACKEND_URL"),
            hotel_backend_timeout=float(_env("HOTEL_BACKEND_TIMEOUT", "10.0")),
            hotel_simulator_enabled=_flag("HOTEL_SIMULATOR", default=True),
            log_level=_env("LOG_LEVEL", "INFO"),
        )

    def has_openai_credentials(self) -> bool:
        return bool(self.openai_api_key or os.environ.get("OPENAI_API_KEY"))


def _env(name: str, default: str | None = None) -> str | None:
    """Read ``HOTEL_ASSISTANCE_<NAME>``, falling back to the bare ``<NAME>``.

    The bare form is what the OpenAI SDK and most local tooling already set,
    so both spellings work; the prefixed one wins when both are present.
    """

    for key in (f"{ENV_PREFIX}{name}", name):
        value = os.environ.get(key)
        if value is not None and value.strip():
            return value.strip()
    return default


def _optional_float(value: str | None) -> float | None:
    return float(value) if value else None


def _flag(name: str, default: bool) -> bool:
    value = _env(name)
    if value is None:
        return default
    return value.lower() not in {"0", "false", "no", "off"}


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()
