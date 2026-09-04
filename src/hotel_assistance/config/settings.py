import os
from enum import StrEnum
from functools import lru_cache

from pydantic import BaseModel


class LLMProviderName(StrEnum):
    OPENAI = "openai"
    OLLAMA = "ollama"


class Settings(BaseModel):
    """Application configuration, sourced from environment variables.

    Provider selection and credentials live here, external to domain/business logic.
    """

    llm_provider: LLMProviderName = LLMProviderName.OLLAMA

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            llm_provider=LLMProviderName(os.environ.get("HOTEL_ASSISTANCE_LLM_PROVIDER", LLMProviderName.OLLAMA)),
            openai_api_key=os.environ.get("HOTEL_ASSISTANCE_OPENAI_API_KEY"),
            openai_model=os.environ.get("HOTEL_ASSISTANCE_OPENAI_MODEL", "gpt-4o-mini"),
            ollama_base_url=os.environ.get("HOTEL_ASSISTANCE_OLLAMA_BASE_URL", "http://localhost:11434"),
            ollama_model=os.environ.get("HOTEL_ASSISTANCE_OLLAMA_MODEL", "llama3.1"),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()
