---
name: llm-provider
description: Implement or modify the provider-independent LLM integration for Hotel Assistance, including OpenAIProvider, OllamaProvider, structured extraction, schema handling, and provider error translation.
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

- Use the OpenAI Responses API.
- Prefer Structured Outputs with a strict schema when supported.
- Keep OpenAI SDK imports and request construction inside the adapter.
- Parse into the same application-owned Pydantic models used elsewhere.

## OllamaProvider

- Use Ollama for local development/testing.
- Keep Ollama-specific request/response handling inside the adapter.
- Normalize and validate output with the same Pydantic/domain rules as OpenAI.

## Structured extraction

The model returns `SearchPatch`, not a complete reconstructed `SearchState`.
Support explicit `add`, `remove`, and `update` filter operations.

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

Test application logic with provider fakes/mocks. Provider-specific integration tests should be separate from default unit tests.
