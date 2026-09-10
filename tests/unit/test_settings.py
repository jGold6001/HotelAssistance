from hotel_assistance.config.settings import RetrievalMode, Settings


def test_defaults_when_environment_is_empty(monkeypatch) -> None:
    for name in ("HOTEL_ASSISTANCE_RETRIEVAL_MODE", "RETRIEVAL_MODE", "HOTEL_ASSISTANCE_FILTER_TOP_K", "FILTER_TOP_K"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings.from_env()

    assert settings.retrieval_mode is RetrievalMode.HYBRID
    assert settings.filter_top_k == 24
    assert settings.openai_model == "gpt-5-mini"


def test_prefixed_variables_are_read(monkeypatch) -> None:
    monkeypatch.setenv("HOTEL_ASSISTANCE_RETRIEVAL_MODE", "keyword")
    monkeypatch.setenv("HOTEL_ASSISTANCE_FILTER_TOP_K", "8")

    settings = Settings.from_env()

    assert settings.retrieval_mode is RetrievalMode.KEYWORD
    assert settings.filter_top_k == 8


def test_bare_variable_names_also_work(monkeypatch) -> None:
    monkeypatch.delenv("HOTEL_ASSISTANCE_OPENAI_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1-mini")

    assert Settings.from_env().openai_model == "gpt-4.1-mini"


def test_prefixed_variable_wins_over_the_bare_one(monkeypatch) -> None:
    monkeypatch.setenv("HOTEL_ASSISTANCE_OPENAI_MODEL", "gpt-5-mini")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1-mini")

    assert Settings.from_env().openai_model == "gpt-5-mini"


def test_credentials_are_detected_from_either_name(monkeypatch) -> None:
    monkeypatch.delenv("HOTEL_ASSISTANCE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert Settings.from_env().has_openai_credentials() is False

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert Settings.from_env().has_openai_credentials() is True


def test_no_ollama_configuration_remains() -> None:
    assert not [name for name in Settings.model_fields if "ollama" in name]
