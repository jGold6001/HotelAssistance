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

| Endpoint                | Purpose                                                                    |
| ----------------------- | -------------------------------------------------------------------------- |
| `GET /health`           | Liveness plus configuration facts (no secrets)                             |
| `POST /api/chat`        | One turn, plain JSON response                                              |
| `POST /api/chat/stream` | One turn as NDJSON: real stage events, the filter summary, then the result |
| `GET /api/state`        | Current search state for a session                                         |
| `POST /api/state/reset` | Clear a session                                                            |

The first request builds the embedding index for the whole registry and caches it in
`.cache/filter_embeddings.json`; later requests only embed the user's message. Editing
`filters.json` changes the cache fingerprint and rebuilds it automatically.

Every turn - from either chat endpoint - is appended to `output/chat_json_<date>.json`, so
the JSON the assistant actually produced for a message can be read back afterwards. The file
is a JSON array of `{timestamp, session_id, user_message, response}` entries; a turn that
failed records `error` in place of `response`. Set `HOTEL_ASSISTANCE_TRANSCRIPT=false` to
turn recording off.

## Docker

```bash
cp .env.example .env          # put the OpenAI key in .env
docker compose up --build     # http://localhost:8000
```

The image installs the pinned dependencies from `uv.lock` and runs uvicorn as an unprivileged
user. Two directories are bind-mounted from the host so they survive restarts: `.cache/` (the
embedding index) and `output/` (chat transcripts). Override the published port with
`HOTEL_ASSISTANCE_PORT=9000 docker compose up`.

For development with hot reload (mounts `./src`, adds `--reload`):

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

## Test

```bash
uv run pytest              # unit tests only, no API calls, no cost
uv run pytest -m integration   # optional, calls the real OpenAI API
```

## Configuration

All variables also work without the `HOTEL_ASSISTANCE_` prefix; see [.env.example](.env.example).

| Variable                | Default        | Notes                                                                |
| ----------------------- | -------------- | -------------------------------------------------------------------- |
| `OPENAI_API_KEY`        | —              | Required                                                             |
| `OPENAI_MODEL`          | `gpt-5-mini`   | Extraction model                                                     |
| `OPENAI_FALLBACK_MODEL` | `gpt-4.1-mini` | Short opening messages only; later turns use `OPENAI_MODEL`          |
| `RETRIEVAL_MODE`        | `hybrid`       | `hybrid`, `semantic`, or `keyword` (no API calls)                    |
| `FILTER_TOP_K`          | `24`           | Candidates sent to the model                                         |
| `HOTEL_BACKEND_URL`     | empty          | Empty means the mock property simulator stands in for a real backend |
| `HOTEL_SIMULATOR`       | `true`         | `false` reports offer counts as unknown instead of simulating them   |
| `TRANSCRIPT`            | `true`         | `false` stops writing the per-day chat transcript                    |
| `TRANSCRIPT_DIR`        | `output`       | Where `chat_json_<date>.json` is written                             |

## Simulated hotel backend

There is no real property backend yet, so with `HOTEL_BACKEND_URL` unset the app simulates one from
the mock database in [src/backend/mock\_db\_hotels/hotels\_100.json](src/backend/mock_db_hotels/hotels_100.json)
(100 properties).

**A complete search runs by itself.** As soon as the state holds a destination, a stay and the
guests, the simulator answers with a count drawn from 0-100 and a table of that many properties —
no directive needed:

```text
Got it: Haarlem, 23-26 Jan 2027 and 1 adults. Applied: Parking.
There are 10 hotels available that match your filters.
```

The draw is seeded by the search state itself, so the same search always reports the same number
and changing a destination, a date or a filter draws a new one. An incomplete search is never
answered: the count stays unknown rather than reporting zero for a search nobody ran.

A tester can still pin the count down with a directive typed into the chat, which overrides the
automatic draw:

```text
@test_aparts = 32          # the backend "found" 32 properties; the table lists them
@test_aparts = 0           # the backend found nothing; the reply offers to widen the search
Quiet room in Haarlem @test_aparts = 5    # works inside a normal request too
```

* **A directive also forces a search on an incomplete state**, which is how the table can be tested
  before a trip is fully specified.

* **`@aparts`** **is accepted as a shorthand**, and a bare `@test_aparts` means zero.

* **Asking for more than the dataset holds repeats entries at random** rather than inventing
  properties; a run is capped at 500 offers and the reply says when it capped one.

* The directive is stripped out of the message before retrieval and extraction see it, so it never
  reaches the model, never lands in the conversation history, and never touches the search state. A
  message that is *only* a directive skips the model entirely — testing the table costs nothing.

## Design notes

**Nothing is invented.** With no hotel backend configured, the count is simulated — explicitly, and
only from the mock database: the simulator draws a number and lists rows straight out of
[hotels\_100.json](src/backend/mock_db_hotels/hotels_100.json), never making up a property or a
price. Nothing downstream treats that number as anything but the backend's answer, so swapping in a
real `HOTEL_BACKEND_URL` changes where the count comes from and nothing else. An incomplete search
still reports `available_offers_count` as `null` rather than guessing at one.

**A turn answers in two messages.** What validation settled is known the moment the patch is
applied; the offer count has to wait for the hotel backend. So the reply is composed in two halves
and streamed as two: the filter summary goes out first, the wait indicator resumes underneath it
reading "Searching available apartments and hotels", and the count and the property table follow.
`POST /api/chat` still returns the whole turn as one `reply`, with `filters_reply` and
`offers_reply` alongside it for callers that want the split.

**A count is stated against the search it answers.** "There are 38 hotels available in Amsterdam for
12-20 Aug 2026 that match your filters" — the same 38 means one thing for a narrow search and
another for a broad one, so the destination, the stay and the fact that filters were applied travel
with the number. Everything but the number comes from the validated state, and the trip is named
once per reply: when the turn already opened with "Got it: Amsterdam, 12-20 Aug 2026 and 2 adults",
the count sentence drops back to "There are 38 hotels available that match your filters".

**A zero-result search ends in an offer, not a dead end.** The reply names what it could give up and
what it would keep, split along the line the user themselves drew:

> No hotels match all of your current filters. I can broaden the search by removing some preferences,
> such as breakfast, desk or reading light, while keeping your required criteria like parking, room
> size (at least 30 m2) and soundproofing. Would you like me to relax those preferences?

It is assembled deterministically from the state and the registry — filters are named by their first
alias, the short form the user would use, rather than by their catalog description. The assistant
never volunteers to drop something the user called a requirement: when *every* filter is required it
says so and asks which one to give up, ranking numeric limits (which can be widened) ahead of
outright removals. Answering "yes" works because a removal may target any filter in the state, even
one this turn's retrieval did not surface.

**A follow-up turn is not a new search.** "I need something in May" is understood against the state
the earlier turns built: Haarlem, one adult and the room preferences stay, only the dates move. When
the user replaces a trip detail without naming a new value, the superseded value is dropped from the
state rather than kept — a stale August stay must not silently reach the backend — and the reply says
what the search still holds before it asks the one open question. Because such a turn is short but
entirely context-dependent, it is never routed to the cheaper model.

The dropped value is not lost: it is remembered on the session as a `PendingTripChange` for as long
as the question stays open, and reaches the model as a `PENDING_CHANGE` prompt section. So "never
mind, keep August" is answered from a recorded value instead of from the model's reading of the
transcript, and it arrives as an ordinary patch that goes through the same date validation as any
other. It is deliberately not part of `SearchState`: an open question is not a validated fact, and
`SearchState` is what reaches the hotel backend. The state panel shows such a detail as waiting on
the user's own words rather than silently blank; the value it superseded stays server-side, because
it is there to be restored, not to be displayed as if it were still in the search.

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
│   │   ├── hotel_search/       # hotel backend client + mock-database simulator
│   │   └── transcript/         # per-day JSON recording of every chat turn
│   ├── config/                 # environment-driven settings
│   └── main.py                 # app wiring; mounts the frontend at /
├── backend/mock_db_hotels/     # mock property database for the simulator
└── frontend/                   # static chat UI (no build step)
```

