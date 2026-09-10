---
name: llm-provider
description: Implement or modify the provider-independent LLM integration for Hotel Assistance, including OpenAIProvider, structured extraction, schema handling, and provider error translation.
---

# LLM Provider Integration

Keep the application independent from provider SDKs.

## Boundary

The application depends on an `LLMProvider`/`LLMClient` interface. Provider adapters may:
- accept an application-level extraction request;
- call the configured LLM backend;
- request structured output;
- normalize output into shared Pydantic models;
- translate provider-specific failures into application-level errors.

Adapters must not own:
- search-state mutation;
- conflict resolution;
- date/range validation;
- hotel availability or prices;
- offer-count logic;
- other domain business rules.

## OpenAIProvider

OpenAI is the only supported provider. Adding another one means writing a new adapter behind
`LLMProvider`, not loosening the interface.

- Use the OpenAI Responses API via `client.responses.parse(..., text_format=ExtractionResult)`,
  which derives a strict Structured Outputs schema from the Pydantic model.
- Keep OpenAI SDK imports and request construction inside the adapter.
- Reasoning-family models (`gpt-5*`, `o1`/`o3`/`o4`) reject an explicit `temperature`; omit it there.
- Short follow-up messages may be routed to the cheaper fallback model.
- Never put backend provenance (`FilterDefinition.source`) into a prompt.

## Structured extraction

The model returns an `ExtractionResult` over a preselected candidate set — not a `SearchPatch`, and
never a reconstructed `SearchState`. The application turns that result into a `SearchPatch` with
explicit `add`, `remove`, and `update` operations after checking every ID against the candidate set
and the registry.

Treat every model response as untrusted:

```text
provider output
 -> parse
 -> Pydantic validation
 -> deterministic domain validation
 -> patch application
```

Do not weaken schemas or domain validation merely to accept a provider response.

## Errors and tests

Translate provider-specific exceptions at the adapter boundary. Do not leak provider SDK exception types into domain/application code.

Test application logic with provider fakes/mocks: pass a fake client into `OpenAIProvider`, or a
fake provider into the orchestrator. Tests that call the real API belong in `tests/integration/`,
marked `integration`, which the default `pytest` run deselects.
