# Current Development State

Updated: 2026-09-05
Branch: main
HEAD: de51e8b
Working tree: dirty — everything except `.gitignore` is untracked (new: `.claude/`, `AGENTS.md`, `CLAUDE.md`, `README.md`, `docs/`, `pyproject.toml`, `src/`, `tests/`, `uv.lock`, `.env.example`); `.gitignore` modified. Nothing beyond the initial commit is in git yet.

## Current Goal
Build Hotel Assistance: an LLM-based parser that turns natural-language hotel requests into structured search-state patches, validated deterministically, per `AGENTS.md`.

## Completed
- Domain models: `SearchState`, `SearchPatch`, `FilterOperation`, `AppliedFilter`, `DateRange`, `GuestConfig`.
- `LLMProvider` Protocol + `LLMExtractionError`, provider-independent.
- `OpenAIProvider` / `OllamaProvider` scaffolds (both explicitly raise "not implemented yet").
- FastAPI app skeleton with `/health` route; `config/settings.py`.
- Unit test suite: 15 tests, all passing.

## Current State
Scaffolding and domain models are done and tested. No orchestration, validation, filter registry, or hotel-backend integration exists yet — `application/`, `domain/services/`, `infrastructure/hotel_search/` are empty packages. LLM providers are non-functional placeholders.

## Last Verification
- `pytest tests/unit -q` → 15 passed (2 unrelated upstream deprecation warnings). Run 2026-09-05.
- Not run: integration tests (none exist yet), lint/type-check, manual FastAPI smoke test.

## Relevant Files
- [AGENTS.md](../../AGENTS.md) — architecture and domain rules of record
- [src/hotel_assistance/infrastructure/llm/provider.py](../../src/hotel_assistance/infrastructure/llm/provider.py)
- [src/hotel_assistance/infrastructure/llm/openai_provider.py](../../src/hotel_assistance/infrastructure/llm/openai_provider.py)
- [src/hotel_assistance/infrastructure/llm/ollama_provider.py](../../src/hotel_assistance/infrastructure/llm/ollama_provider.py)
- [src/hotel_assistance/domain/models/search_state.py](../../src/hotel_assistance/domain/models/search_state.py)
- [src/hotel_assistance/domain/models/search_patch.py](../../src/hotel_assistance/domain/models/search_patch.py)
- [src/hotel_assistance/application/](../../src/hotel_assistance/application/) — empty, next to implement (ChatOrchestrator)
- [src/hotel_assistance/domain/services/](../../src/hotel_assistance/domain/services/) — empty, next to implement (SearchValidator, FilterRegistry)
- [.claude/skills/filter-registry/SKILL.md](../../.claude/skills/filter-registry/SKILL.md)
- [.claude/skills/llm-provider/SKILL.md](../../.claude/skills/llm-provider/SKILL.md)

## Next Step
Implement the JSON/YAML filter registry (schema + loading + validation) per `.claude/skills/filter-registry/SKILL.md`, since both `SearchValidator` and LLM candidate-preselection depend on it.

## Open Questions
- Should the current untracked work be committed, and in what grouping (single commit vs. per-layer)?
- None else at this stage.

## Source Report
- docs/work-reports/2026-09-05.md
