# Hotel Assistance

Turns a natural-language hotel request into a structured, validated search state.
The assistant only sets filters; the non-AI hotel backend does the actual searching.

```text
user message
  -> candidate retrieval (438-filter registry -> ~24 candidates)
  -> OpenAI structured extraction (ExtractionResult)
  -> deterministic patch building + validation
  -> SearchState
  -> hotel backend (offer count only)
```

The retriever answers **which filters might be relevant**. The LLM answers **which of those the
user actually asked for, and with what values**. Everything after that — conflicts, bounds, date
ranges, what the reply is allowed to claim — is deterministic application code.

See [AGENTS.md](AGENTS.md) for the architecture and domain invariants.

## Setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env      # then set HOTEL_ASSISTANCE_OPENAI_API_KEY
```

OpenAI is the only supported LLM provider.

## Run

```bash
uv run uvicorn hotel_assistance.main:app --reload
```

Open <http://localhost:8000> for the chat UI. The API is on the same port:

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Liveness plus configuration facts (no secrets) |
| `POST /api/chat` | One turn, plain JSON response |
| `POST /api/chat/stream` | One turn as NDJSON: real stage events, then the result |
| `GET /api/state` | Current search state for a session |
| `POST /api/state/reset` | Clear a session |

The first request builds the embedding index for the whole registry and caches it in
`.cache/filter_embeddings.json`; later requests only embed the user's message. Editing
`filters.json` changes the cache fingerprint and rebuilds it automatically.

## Test

```bash
uv run pytest              # unit tests only, no API calls, no cost
uv run pytest -m integration   # optional, calls the real OpenAI API
```

## Configuration

All variables also work without the `HOTEL_ASSISTANCE_` prefix; see [.env.example](.env.example).

| Variable | Default | Notes |
| --- | --- | --- |
| `OPENAI_API_KEY` | — | Required |
| `OPENAI_MODEL` | `gpt-5-mini` | Extraction model |
| `OPENAI_FALLBACK_MODEL` | `gpt-4.1-mini` | Used for short follow-ups |
| `RETRIEVAL_MODE` | `hybrid` | `hybrid`, `semantic`, or `keyword` (no API calls) |
| `FILTER_TOP_K` | `24` | Candidates sent to the model |
| `HOTEL_BACKEND_URL` | empty | Empty means offer counts are reported as unknown |

## Design notes

**Nothing is invented.** With no hotel backend configured, `available_offers_count` is `null`, not a
guess. Zero-result relaxation advice is derived from the filters the user actually set — preferences
first, then numeric limits that can be widened, then hard requirements.

**Conflicts are not resolved by the model.** When a requested filter conflicts with an active one,
the new filter is refused, the conflict is stated, and the user is asked which side to keep. A single
message may still swap sides: removals within a patch are applied before additions.

**Retrieval is hybrid on purpose.** Embedding a long, multi-request message produces one averaged
vector, which buried `room.size_m2` at rank 156 for a message that literally said "at least 30 square
meters". Reserving slots for exact alias matches fixes that without losing paraphrase matching.

## Project layout

```text
src/
├── backend/hotel_assistance/
│   ├── api/                    # thin FastAPI routes, transport schemas, composition root
│   ├── application/            # orchestration, patch building, reply composition, sessions
│   ├── domain/
│   │   ├── models/             # SearchState, SearchPatch, ExtractionResult, ...
│   │   ├── registry/           # filters.json (438 canonical filters)
│   │   └── services/           # registry, validator, retrieval, relaxation
│   ├── infrastructure/
│   │   ├── embeddings/         # OpenAI embeddings adapter
│   │   ├── llm/                # LLMProvider interface + OpenAI adapter + prompts
│   │   ├── retrieval/          # semantic and hybrid retrievers
│   │   └── hotel_search/       # hotel backend client
│   ├── config/                 # environment-driven settings
│   └── main.py                 # app wiring; mounts the frontend at /
└── frontend/                   # static chat UI (no build step)
```

## Language

- Use English only in code: identifiers, comments, docstrings, commit messages, log messages, and
  error messages.
- Non-code chat replies may be in the language the user writes in.
