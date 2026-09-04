from hotel_assistance.config.settings import LLMProviderName, Settings


def test_settings_default_to_ollama_when_env_unset(monkeypatch) -> None:
    monkeypatch.delenv("HOTEL_ASSISTANCE_LLM_PROVIDER", raising=False)

    settings = Settings.from_env()

    assert settings.llm_provider == LLMProviderName.OLLAMA


def test_settings_read_provider_from_env(monkeypatch) -> None:
    monkeypatch.setenv("HOTEL_ASSISTANCE_LLM_PROVIDER", "openai")

    settings = Settings.from_env()

    assert settings.llm_provider == LLMProviderName.OPENAI
