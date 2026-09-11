# AGENTS.md

## Project
Hotel Assistance converts natural-language hotel requests into structured search-state updates. The assistant sets filters; the non-AI hotel backend performs the real search.

Architecture: **Stateful LLM Filter Parser with Deterministic Validation**.

Source-of-truth boundaries:
- **LLM:** interprets language and produces structured intent.
- **Application/backend:** validation, conflicts, state transitions, and business rules.
- **Hotel backend:** offers, prices, availability, and `available_offers_count`.

Prefer simple, deterministic, testable code. Never move business-critical decisions into the LLM when deterministic validation is possible.

## Stack
Default stack:
- Python 3.12+, FastAPI, Pydantic v2
- OpenAI Responses API (the only supported LLM provider)
- OpenAI embeddings for filter candidate retrieval
- `uv` + `pyproject.toml`
- `pytest`, `httpx`
- JSON/YAML filter registry
- in-memory state for the test/demo

Use strict structured output when supported. Treat all LLM output as untrusted until Pydantic and domain validation succeed.

Do not add LangChain, LangGraph, multi-agent architecture, Kafka, Kubernetes, Redis, PostgreSQL/pgvector, or a standalone vector DB unless a concrete requirement justifies it.

## Layout
`src/backend/hotel_assistance/` holds the Python package; `src/frontend/` holds the static chat UI
(plain HTML/CSS/JS, no build step) that FastAPI mounts at `/`. Keep the two apart: the backend
serves JSON and never renders markup, the frontend holds no business rules.

## Architecture
Keep FastAPI routes thin: validate transport input, call an application service, return the result.

```text
API
 -> ChatOrchestrator
    -> CandidateRetriever
       -> SemanticCandidateRetriever (OpenAI embeddings + cached index)
       -> KeywordCandidateRetriever (deterministic aliases)
       -> HybridCandidateRetriever (both; the default)
    -> LLMProvider
       -> OpenAIProvider
    -> FilterRegistry
    -> SearchValidator
    -> SearchState
    -> HotelSearchClient
```

Provider-specific SDK code stays inside adapters. Business logic must not depend on OpenAI types.

`LLMProvider` accepts an `ExtractionRequest`, returns an `ExtractionResult`, and translates provider errors. It must not own state mutation, conflict rules, date/range validation, availability, or offer-count logic.

For provider implementation details, use `.claude/skills/llm-provider/SKILL.md`.

## Data Models
Prefer explicit Pydantic models: `SearchState`, `SearchPatch`, `FilterOperation`, `FilterDefinition`, `DateRange`, `GuestConfig`.

The LLM returns an `ExtractionResult`, which the application turns into a `SearchPatch` — never a
reconstructed full state. Support explicit `add`, `remove`, and `update` operations. Preserve valid
state unless the user changes it.

```text
candidates + message -> ExtractionResult -> SearchPatch -> validate -> new_state
```

Assistant replies are composed deterministically from what validation actually applied, so a reply can
never claim a filter the validator refused. Only the clarification question comes from the model.

## Domain Rules
- Extract destination, dates, and guests whenever present.
- If required data is missing or ambiguous, ask a concise clarification question; do not guess.
- Validate dates, ranges, units, bounds, allowed values, and filter types deterministically.
- Support boolean and range filters.
- Detect conflicting or impossible combinations with explicit rules.
- Do not let the LLM silently choose which side of a conflict to keep.
- Preserve unchanged state while supporting add/remove/update operations.
- Reject requests unrelated to hotel-search filters.
- For zero results, use backend data and current state to suggest filter relaxation; never fabricate hotels.
- Never invent availability, prices, offers, or `available_offers_count`.

## Filter Registry
Use canonical filter IDs. Never persist arbitrary LLM-generated filter names. For large registries,
preselect relevant candidates before LLM extraction instead of sending the entire registry.

Retrieval modes (`HOTEL_ASSISTANCE_RETRIEVAL_MODE`): `hybrid` (default), `semantic`, `keyword`.
Retrieval is allowed to be fuzzy — every candidate ID it returns is re-checked against the registry
before it can reach the state.

For registry schema, retrieval, validation, and bulk-edit rules, use `.claude/skills/filter-registry/SKILL.md`.

## State and Backend
Use simple in-memory state for the demo/test task. Apply patches only after validation.

Use `httpx` for hotel-backend integration. The hotel backend is the only source of truth for real deals, prices, availability, and matching-offer counts.

## Testing
Use `pytest`.

- Run the narrowest relevant tests first.
- Mock external LLM and hotel-backend calls in default unit tests.
- Default tests must never make paid OpenAI API calls.
- OpenAI-backed tests are optional integration tests, marked `integration` and deselected by default.
- Cover search-state updates, conflicts, clarification, zero-result behavior, and invalid structured LLM output.

## Code and Configuration
Follow repository conventions. For new Python code:
- follow PEP 8 and use type hints;
- keep functions focused;
- prefer composition over inheritance-heavy designs;
- keep side effects at integration boundaries;
- avoid unnecessary abstractions beyond required boundaries.

All code comments, docstrings, GitHub issues, PRs, and commit messages must be in English.

Keep provider selection/configuration outside domain logic. Never hardcode, commit, expose, or log secrets/API keys.

Fail explicitly on invalid structured output, validation errors, invalid state transitions, conflicts, and unrecoverable provider/backend failures.

## Change Discipline
Inspect nearby code before editing and follow existing patterns. Make the smallest coherent change; do not refactor unrelated code or add dependencies unnecessarily.

Ask for approval before:
- adding/upgrading dependencies;
- deleting files;
- changing public API contracts beyond scope;
- introducing production infrastructure;
- committing, pushing, merging, or deploying unless explicitly requested.

Reading/editing requested files and running targeted local checks do not require extra approval.

Run relevant checks before declaring work complete and report anything not run.

## Scope
This project originates from a time-boxed AI Engineer test task. Prioritize clarity of architecture and reasoning over infrastructure completeness.

Base scope: **FastAPI + provider-independent LLMProvider + OpenAI + Structured Outputs + Pydantic + JSON registry with candidate retrieval + in-memory state + static chat frontend + pytest.**
