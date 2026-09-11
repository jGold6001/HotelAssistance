# Current Development State

Updated: 2026-09-10
Branch: feat/project-remake
HEAD: 9d9853e
Working tree: dirty — full vertical slice implemented but almost entirely uncommitted. Package
moved `src/hotel_assistance/` → `src/backend/hotel_assistance/` (mostly renames); new untracked
dirs: `src/backend/.../api/{chat,dependencies,schemas}.py`, `application/` (orchestrator, patch
builder, reply composer, session store), new domain models/services (validator, retriever,
relaxation), `infrastructure/embeddings/`, `infrastructure/retrieval/`, `src/frontend/`; plus
matching new/updated tests. `Ollama` provider deleted. Docs (`README.md`, `AGENTS.md`,
`.env.example`, skill files) and `pyproject.toml` also modified.

## Current Goal
Build Hotel Assistance: an LLM-based parser that turns natural-language hotel requests into
structured search-state patches, validated deterministically, per `AGENTS.md`.

## Completed
- Full pipeline implemented: candidate retrieval (hybrid semantic+keyword) → `OpenAIProvider`
  (Structured Outputs) → `patch_builder` → `SearchValidator` → `SearchState` → `HotelSearchClient`.
- `ChatOrchestrator` wiring the whole turn, with stage callbacks for `/api/chat/stream` (NDJSON).
- 438-filter JSON registry (433 boolean, 5 range, 32 with conflict rules) with `FilterRegistry`.
- FastAPI routes (`/api/chat`, `/api/chat/stream`, `/health`) + static frontend mounted at `/`.
- Ollama provider removed; OpenAI is now the sole supported provider.
- Unit test suite grew to 139 tests (from 15 on 2026-09-05); `integration` pytest marker added
  and excluded by default.

## Current State
Feature-complete vertical slice for the base scope (chat → structured patch → validated state →
offer count → reply). Not yet committed to git beyond `9d9853e`. No lint/type-check run this
session; no live/manual smoke test of the API or frontend confirmed this session.

## Last Verification
- `python3 -m pytest tests/unit -q` → 139 passed, 1 unrelated deprecation warning. Run 2026-09-10.
- Not run: integration tests (need real OpenAI key), lint/type-check, manual FastAPI/frontend
  smoke test.

## Relevant Files
- [AGENTS.md](../../AGENTS.md) — architecture and domain rules of record
- [src/backend/hotel_assistance/application/chat_orchestrator.py](../../src/backend/hotel_assistance/application/chat_orchestrator.py)
- [src/backend/hotel_assistance/domain/services/search_validator.py](../../src/backend/hotel_assistance/domain/services/search_validator.py)
- [src/backend/hotel_assistance/domain/services/filter_registry.py](../../src/backend/hotel_assistance/domain/services/filter_registry.py)
- [src/backend/hotel_assistance/infrastructure/llm/openai_provider.py](../../src/backend/hotel_assistance/infrastructure/llm/openai_provider.py)
- [src/backend/hotel_assistance/infrastructure/retrieval/hybrid_retriever.py](../../src/backend/hotel_assistance/infrastructure/retrieval/hybrid_retriever.py)
- [src/backend/hotel_assistance/api/chat.py](../../src/backend/hotel_assistance/api/chat.py)
- [src/frontend/](../../src/frontend/) — static chat UI
- [pyproject.toml](../../pyproject.toml)
- [README.md](../../README.md)

## Next Step
Decide on commit granularity and commit the current uncommitted working tree (backend restructure,
frontend, tests, docs), then run any configured lint/type-check before/along with that commit.

## Open Questions
- Commit strategy: single commit vs. split by layer?
- Is a lint/type-check tool configured, and does it currently pass?
- Has `/api/chat` + frontend been manually smoke-tested end-to-end against a real OpenAI key?

## Source Report
- docs/work-reports/2026-09-10.md
