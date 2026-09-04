# Hotel Assistance

AI-assisted hotel search filter parser. The assistant converts natural-language
hotel requests into structured search-state updates; the non-AI hotel backend
performs the actual search after the user applies them.

See [AGENTS.md](AGENTS.md) for the full architecture and domain invariants.

## Setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env
```

Edit `.env` to select the LLM provider (`ollama` for local development,
`openai` for production) and set provider-specific configuration.

## Run

```bash
uv run uvicorn hotel_assistance.main:app --reload
```

The API is served at `http://localhost:8000`; check `GET /health` for a
liveness probe.

## Test

```bash
uv run pytest
```

## Project layout

```text
src/hotel_assistance/
├── api/              # thin FastAPI routes
├── application/       # orchestration between API, LLM, and domain layers
├── domain/
│   ├── models/        # SearchState, SearchPatch, FilterOperation, ...
│   └── services/       # deterministic validation and business rules
├── infrastructure/
│   ├── llm/            # LLMProvider interface, OpenAI/Ollama adapters
│   └── hotel_search/   # hotel backend client
└── config/             # environment-driven settings
```

## Status

Initial scaffold only. The LLM providers and hotel search integration are
placeholders; see AGENTS.md for the intended production evolution.
