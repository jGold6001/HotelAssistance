# Hotel Assistance — Assistant Design (Concise Version)

**Test task for the AI Engineer position at WinWin.travel.** This document covers items 1, 2, 3 and 5 of the task; item 4 (Example JSON output) is delivered separately. The full version — with the verbatim system prompt and the complete list of all 438 filter IDs — is here: [Hotel Assistance — AI Assistant Design (full version)](https://docs.google.com/document/d/1LBZdluqlRFuBXOQbCynUcPlSRIE5vgLLa6DM52I1zpg/edit).

Everything below is implemented and running: a FastAPI backend with a static chat UI, a 438-filter registry, OpenAI Structured Outputs extraction, deterministic validation, and 240 unit tests that make no paid API calls.

## 0. The design in one paragraph

**A stateful LLM filter parser with deterministic validation.** The model does exactly one thing: it interprets language into structured intent. Everything else — validation, conflicts, bounds, state transitions, the reply text — is deterministic application code, and offers, prices and counts come only from the hotel backend. A reply can therefore never claim a filter that validation refused: it is composed from the validation result, and the only sentence the model contributes is the clarification question.

```text
message -> retrieval (438 filters -> ~24 candidates)
        -> OpenAI Structured Outputs (ExtractionResult)
        -> patch build (untrusted IDs re-checked, dates parsed)
        -> validation (types, bounds, conflicts, state merge)
        -> SearchState -> hotel backend (offer count) -> deterministic reply
```

---

## 1. Assistant configuration (OpenAI settings)

| Setting | Value |
| --- | --- |
| API | OpenAI **Responses API**, `client.responses.parse(...)` with **Structured Outputs**: `text_format=ExtractionResult` (Pydantic v2 → strict JSON schema, parsed straight back into the typed model) |
| Extraction model | `gpt-5-mini` |
| Fallback model | `gpt-4.1-mini` — only for a short **opening** message (≤ 12 words, no history). A short *later* turn ("I need something in May") is never downgraded: it only means anything against the current state, which is exactly what a weaker model misreads |
| `temperature` | Unset; never sent to reasoning-family models (`gpt-5`, `o1`, `o3`, `o4`), which reject it |
| Embeddings | `text-embedding-3-small`; the registry index is cached on disk, keyed by a registry fingerprint plus the model name |
| Candidates per turn | `FILTER_TOP_K = 24`, with 6 slots reserved for verbatim alias matches (hybrid retrieval) |
| Tools / memory | None. One model call per turn; conversation state belongs to the application |

**Input per turn** is a small labelled envelope — never the whole registry, never the whole transcript: `TODAY`, `CURRENT_STATE` (the validated state), `CANDIDATE_FILTERS` (~24 entries: id, type, description, aliases, unit), `PENDING_CHANGE` (an open trip question, when there is one), `CONVERSATION_SO_FAR`, `USER_MESSAGE`.

**Instructions**, condensed (the verbatim text is in the full version, §1.4):

- Report only what *this* message changes; `CURRENT_STATE` stays in force. Never re-emit a filter it already holds, never ask for a detail it already has.
- Use only IDs from `CANDIDATE_FILTERS`; never invent or reshape an ID. Candidates are retrieved by similarity, so ignore near-misses. Map meaning, not keywords.
- `op` is `add`, `update` or `remove`. If the user changed their mind about a filter in state, emit `remove` for the old one and `add` for the new one.
- If one message asks for two things that cannot both hold, emit **both** exactly as read. Do not pick a side — the application detects the conflict and asks.
- `strength` is `required` for explicit requirements and `preferred` for soft wording (ideally, bonus, nice to have).
- Boolean filters use `boolean_value` only; range filters use `range_value` only ("at least X" → min, "at most X" → max, "between" → both).
- `unmapped_requests` holds property or room features no candidate expresses, quoted. Never a destination, a date, a guest count or a vague wish.
- Fill destination, check-in, check-out and guests whenever present. Dates are ISO 8601, resolved against `TODAY` to the next future occurrence.
- A vague trip change ("something in May", "worldwide") leaves the field null, keeps the user's words in `date_hint` / `destination_hint`, and asks. Never carry the superseded value forward, never invent a replacement.
- `is_hotel_search_related=false` only when the message has nothing to do with hotel search; an under-specified hotel request is asked about, not rejected. One concise `clarification_question`, only about what is genuinely unknown. Do not guess.

**Output contract** (strict): `is_hotel_search_related`, `reset_requested`, `filters[]` (`filter_id`, `op`, `type`, `strength`, `boolean_value` | `range_value{min,max}`), `unmapped_requests[]`, `trip` (`destination`, `destination_hint`, `check_in`, `check_out`, `date_hint`, `guests{adults,children}`), `missing_trip_info[]`, `clarification_question`. Pydantic enforces that a boolean filter carries only `boolean_value`, a range filter only `range_value`, and a removal no value at all.

**Failures are explicit.** Provider errors become `LLMExtractionError` (HTTP 502); a refusal or schema-invalid output is a hard failure, never a silent empty extraction; a hotel-backend outage reports the count as unknown and keeps the filter work the user just did. Every turn is recorded to `output/chat_json_<date>.json`.

---

## 2. Filters list

Canonical, namespaced, stable IDs in a JSON registry. Arbitrary LLM-generated filter names are never persisted.

```json
{"id": "room.size_m2", "type": "range", "description": "Room floor area",
 "aliases": ["room size", "large room", "spacious room", "square meters"],
 "unit": "m2", "bounds": {"min": 0, "max": 500}, "conflicts_with": []}
```

Fields: `id`, `type` (`boolean` | `range`), `description`, `aliases` (how a traveller says it; the first alias is the short spoken form used in replies), `unit` (required for ranges), `bounds`, `conflicts_with` (applied symmetrically), `source` (provenance in the backend facility catalog; never sent to the model). Integrity — duplicate IDs, unknown conflict targets, a range without a unit — is checked at startup.

**Current registry: 438 filters — 433 boolean, 5 range**, derived from a real property/room facility catalog. `hotel.*` 241 · `room.*` 193 · `rating.*` 2 · `price.*` 1 · `distance.*` 1.

By theme: Food & drink 54 · Room comfort & bedding 50 · Wellness, spa & fitness 47 · Services & front desk 42 · Entertainment & activities 38 · Connectivity & media 33 · Pool, beach & water 27 · Safety, security & health 27 · Bathroom & toiletries 24 · Accessibility 20 · Views & outdoor space 19 · Parking & transport 17 · Kids & family 16 · Work & business 7 · Property & unit type 6 · Pets & smoking 5 · Price, rating & location 4 · Sustainability & payment 2.

| Range filter | Unit | Bounds |
| --- | --- | --- |
| `price.per_night` | EUR | min 0 |
| `room.size_m2` | m2 | 0–500 |
| `rating.stars` | stars | 1–5 |
| `rating.guest_score` | points | 0–10 |
| `distance.to_center_km` | km | min 0 |

32 filters declare conflicts, for example `hotel.adult_only` ↔ 16 child/family filters, `hotel.non_smoking_rooms` ↔ `hotel.designated_smoking_area`, `hotel.airport_shuttle_free` ↔ `hotel.airport_shuttle_surcharge`, `room.feather_pillow` ↔ `room.non_feather_pillow`.

**Getting to 1000+.** The architecture already assumes it: the registry is never sent to the model, so prompt size, latency and cost are flat in registry size. The remaining ~600 filters come from mechanical expansion of what the catalog already implies, not from invention: paid/free variants (~60); more **range** filters — distance to beach/airport/station, bedrooms and bathrooms, floor, check-in windows, stay length, cancellation deadline (~40); a bed-configuration matrix (~25); view and location typology (~30); cuisine and dietary detail (~50); staff languages (~40); accessibility detail codes (~40); property character — boutique, family-run, independent (~30); policy filters. Two rules matter more than the count: no semantically equivalent IDs, and conflicts declared the moment a filter is added. The complete list of all 438 IDs is Appendix A of the full version.

---

## 3. How the assistant works

**Understanding and extraction.** Seven stages per turn; only the second involves the model.

1. *Retrieval* — hybrid: cosine similarity on embeddings catches paraphrase ("I hate hearing hallway noise" → soundproofing), and a reserved lane of rarity-weighted exact alias matches catches specific asks. The lane exists because of a measured failure: a long message's single averaged embedding buried `room.size_m2` at rank 156 when the text literally said "at least 30 square meters".
2. *LLM extraction* — which candidates the user actually asked for, with what values and at what strength.
3. *Patch build — the trust boundary.* Every ID must be in this turn's candidate set *and* in the registry; the type must match; dates are really parsed; guest counts validated. Anything dropped becomes an explicit issue.
4. *Validation* — bounds, conflicts, date range; `add` / `remove` / `update` applied as a patch, unchanged state preserved.
5. *Search* — only once destination, full stay and guests are known. An incomplete search reports the count as `null`, never as zero.
6. *Deterministic reply* — distinguishes Applied, Removed and Excluding.
7. *Recording* to the JSON transcript.

A real turn (task message 1, run on 2026-09-10): *"Got it: Haarlem, 15-18 Aug 2027 and 1 adult. Applied: Room floor area (at least 30 m2), Room has internet facilities, Room has good soundproofing from hallway, street, or bar noise, Room has reading light, Room has shower and Property offers communal lounge / TV room. I could not map these to a supported filter, so they are not part of the search: family-run or boutique (not a big chain); real double bed…"* — August resolved to 2027 because August 2026 had already passed, and "traveling solo" became 1 adult. The follow-up *"I need something in May"* is read against that state: *"I still have Haarlem, 1 adult and 6 saved preferences. Which dates in May — and which year — would you like for check-in and check-out?"*

**Incorrect, conflicting or impossible filters.** The model never resolves a conflict. Four classes are handled separately:

- *Invalid or hallucinated IDs* — not among the candidates, not in the registry, or the wrong type — are dropped with an explicit issue.
- *Impossible values* — out-of-bounds ranges, a check-out not after the check-in, an impossible guest count — are refused with the reason named.
- *A new filter against an active one* (registry `conflicts_with`, symmetric): the new filter is **refused** and the user picks. *"'Property offers family rooms' conflicts with 'Property accepts adults only', which is already active. Tell me which of the two you want to keep and I will switch it over."* A filter set to `false` states an absence and never conflicts; removals apply before additions, so "no, make it a smoking room" swaps sides in one turn.
- *Self-contradiction* — "pet-friendly" and "no pets" in one message is the **same** filter with two values, which `conflicts_with` cannot see. The validator catches two non-removal operations on one `filter_id` with different values and applies **neither**: *"You asked for two different values for 'Property allows pets' in the same message. Tell me which of the two you want to keep and I will switch it over."*

**No hotels match.** The zero comes only from the backend; nothing about availability is ever invented. The reply proposes a way out, split along the line the user drew between requirements and preferences: *"No hotels match all of your current filters. I can broaden the search by removing some preferences, such as breakfast, desk or reading light, while keeping your required criteria like parking, room size (at least 30 m2) and soundproofing. Would you like me to relax those preferences?"* Relaxations are ranked — preferences first, then numeric limits (widened rather than dropped), then hard requirements — and the assistant never volunteers to drop a requirement: when everything is required it says so and asks which one to give up. Non-zero counts are stated against the search they answer: *"There are 38 hotels available in Amsterdam for 12-20 Aug 2026 that match your filters."*

**Clarifying questions.** One per turn, only about what is genuinely unknown. The model phrases it; the application decides what is missing from the validated state, so the assistant can never ask for what it already holds. Every question restates what the search still holds. A vague change drops the superseded value from the state — a stale August stay must not reach the backend — but remembers it server-side as a `PendingTripChange`, so *"never mind, keep August"* is restored from a recorded value through normal validation. Unsupported requests are named in the reply, never silently dropped, and double as the best signal for which filters the registry is missing.

**Unrelated questions.** `is_hotel_search_related=false` produces a fixed, application-composed refusal; the state is untouched and the reply says so: *"Your current search is unchanged: Haarlem, 22-23 Nov 2026, 1 adult and 6 saved preferences."* Under-specified is not unrelated: "Suggest best deals worldwide" gets a question, not a refusal. And rejection is not the only defence — instruction-shaped text has no path to the state, because every ID, value and reply passes through deterministic checks.

---

## 5. How to A/B test this assistant

Every turn's output is a **typed object** — `SearchState`, issues, offer count — so variants are compared by diffing state rather than judging prose, and the transcript already records every turn as JSON.

**Layer 1 — offline replay gates the release.** A gold set of 300–500 real, labelled turns: long messages, state-dependent follow-ups, vague changes, conflicts, removals, zero results, out-of-scope, non-English. Metrics: **trip-field accuracy** (exact destination, dates, guests — a blocking gate, not a trade-off), filter precision/recall (precision matters more: a wrong filter silently narrows the search), strength accuracy, **retrieval recall@24** (separates retrieval failures from extraction failures), out-of-scope false refusals/accepts, schema failure rate, cost and p95 latency. Retrieval-only changes are evaluated with zero model calls.

**Layer 2 — online A/B decides.** Sticky assignment per session (never per turn), the variant recorded on every transcript entry. Primary metric: **search-to-apply conversion**. Guardrails: turns to first complete search; **filter-undo rate** — the user removing a filter the assistant just set is the sharpest quality signal there is; zero-result rate and recovery after a relaxation offer; clarification rate (two-sided: too many is friction, too few is guessing); unmapped-request rate; abandonment; latency and cost. Run at least two full weekly cycles, fix the sample size from the MDE, and use a sequential test if peeking early.

**Order of experiments:** (1) model routing — `gpt-5-mini` everywhere vs the short-opening fallback to `gpt-4.1-mini`; (2) retrieval — `top_k` 16/24/32 and keyword quota 4/6/8, measured by interleaving; (3) question policy — one unknown per turn vs two related ones; (4) zero-result wording, and asking before relaxing vs auto-relaxing preferences; (5) confirmation verbosity.

**Do not A/B business rules.** Conflicts, bounds, dates and state merging are correctness and live in `pytest` (240 tests today); a variant that "wins" by silently keeping one side of a conflict has hidden a defect. Add shadow mode for new models (run in parallel, serve the incumbent, log both) and a small blind human-rated sample (100–200 turns per variant) as calibration for the automated metrics.
