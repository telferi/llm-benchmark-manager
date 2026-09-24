# LLM Benchmark Manager v0.2 — Capability-Aware Testing and Progress

Date: 2026-09-24
Status: design for review
Base: v0.1.0 implementation on `feature/implementation-v1`

## 1. Purpose

v0.2 corrects classification and observability problems exposed by the first real NVIDIA full-catalog run. That run processed 82 discovered models in about 43 minutes and ended with 9 ACTIVE, 14 UNSTABLE, and 59 FAILED. Of the 59 FAILED models, 55 were HTTP 404 `MODEL_NOT_FOUND` responses indicating catalog/account availability rather than a broken model. Other false negatives came from sending chat/text requests to embedding, parser, vision, translation, safety, or otherwise specialized models, and from response shapes where useful output was not in `message.content`.

The goal is to distinguish model health from provider availability and test compatibility, while making long runs visibly trackable.

## 2. Scope

v0.2 adds:

- accurate per-model run progress;
- capability detection and persistence;
- capability-aware smoke testing;
- response extraction tolerant of common OpenAI-compatible variants;
- refined status classification;
- error-specific retry policies;
- stronger provider-message sanitization;
- run-progress access from CLI, REST, and MCP;
- capability-aware benchmark eligibility so incomparable models are not forced through the same AIPerf profile.

v0.2 does not add a web dashboard, distributed workers, automatic Hermes routing changes, or provider-specific benchmark implementations for every special NVIDIA model family.

## 3. Status model

`ModelStatus` becomes:

- `NEW` — discovered but not yet evaluated;
- `ACTIVE` — passed an appropriate supported test and benchmark where applicable;
- `UNSTABLE` — works, but transient failures or partial benchmark failures were observed;
- `NOT_AVAILABLE` — listed by discovery but not callable with the current provider/account/endpoint (for example a consistent 404 function-not-available response);
- `INCOMPATIBLE` — the attempted generic API shape is not valid for this model and a different capability-specific request is required;
- `UNSUPPORTED` — capability is known but v0.2 has no safe generic test/benchmark for it;
- `FAILED` — a capability-appropriate, supported request produced a definitive non-transient failure;
- `DISABLED` — manually excluded;
- `MISSING` — previously known but no longer returned by discovery.

A 404 must not become `FAILED`. A 400 caused by a capability mismatch must not become `FAILED`. `FAILED` is reserved for evidence that the model failed under the correct supported test path.

Existing historical rows are not rewritten. A later retest may transition an old `FAILED` model into `NOT_AVAILABLE`, `INCOMPATIBLE`, `UNSUPPORTED`, `ACTIVE`, or `UNSTABLE` with status history preserved.

## 4. Capability model

Add `ModelCapability` values:

- `CHAT_TEXT`
- `EMBEDDING`
- `VISION`
- `MULTIMODAL`
- `PARSER`
- `TRANSLATION`
- `SAFETY`
- `RERANK`
- `SPECIAL`
- `UNKNOWN`

Each model stores:

- capability;
- capability source: `metadata`, `model_id_heuristic`, `probe`, or `manual`;
- optional confidence score or confidence class;
- original provider metadata unchanged in `metadata_json`.

Detection precedence:

1. explicit provider discovery metadata;
2. provider adapter rules;
3. conservative model-id heuristics;
4. probe/error feedback;
5. otherwise `UNKNOWN`.

Heuristics must be conservative. Examples such as `embed`, `embedqa`, `retriever`, `clip` can suggest embedding; `vision`, `vlm`, `vila`, `fuyu` can suggest vision/multimodal; `translate` translation; `parse` parser; `guard`, `safety`, `content-safety` safety. A heuristic never by itself proves that the model is broken or callable.

## 5. Capability-aware smoke testing

The provider adapter exposes capability-oriented probe methods rather than one universal chat probe.

### CHAT_TEXT

Use `/v1/chat/completions` with a small deterministic text prompt.

Success output extraction checks, in order:

- `choices[0].message.content` as string;
- text items inside structured `message.content` arrays;
- `choices[0].message.reasoning_content` when non-empty;
- `choices[0].text`;
- compatible top-level/output-text variants implemented by the adapter.

Usage metadata, null content, empty arrays, or `[DONE]` alone are not success.

### EMBEDDING

Use `/v1/embeddings` with a tiny text input when the provider follows the OpenAI-compatible embedding shape. Validate that at least one non-empty numeric embedding vector is returned. Embedding models are not sent to chat completions.

### VISION / MULTIMODAL

v0.2 may perform a minimal multimodal chat probe only when the adapter explicitly supports a known request format and a bundled deterministic tiny image fixture is available. Otherwise classify as `UNSUPPORTED`, not `FAILED`.

### PARSER / TRANSLATION / SAFETY / RERANK / SPECIAL

Only probe when the adapter has a documented generic request path for that capability. Otherwise classify `UNSUPPORTED` and preserve the model for future provider-specific adapters.

### UNKNOWN

Attempt a conservative chat-text probe only when provider metadata suggests OpenAI chat compatibility. If the response clearly says text input is unsupported, classify `INCOMPATIBLE`, update capability hints from the error, and do not retry the same payload.

## 6. Availability and error classification

Normalize errors with context, not status code alone.

- 401/403 -> `AUTH_ERROR`; run/provider credential problem, not model failure.
- 404 on model invocation -> `NOT_AVAILABLE`; no retry.
- 429 -> `RATE_LIMITED`; transient, model becomes/stays `UNSTABLE` if eventually usable.
- 503 -> `OVERLOADED`; transient, `UNSTABLE` if eventually usable.
- 500/502/504 -> `PROVIDER_ERROR`; transient with bounded retry.
- timeout/network reset -> `TIMEOUT` / `NETWORK_ERROR`; transient with bounded retry.
- 400 with recognized capability mismatch -> `INCOMPATIBLE`; no retry of identical payload.
- 400 with a supported capability and valid request -> `PAYLOAD_ERROR`; record separately and only classify `FAILED` when evidence indicates a real model/request failure rather than wrong capability.
- HTTP 200 with no recognized output -> `EMPTY_RESPONSE`; response parser tries supported alternate fields before classification.

## 7. Retry policy

Replace one retry schedule for every transient error with error-specific policies:

- 404, auth errors, capability mismatch, deterministic payload errors: 0 retries;
- 429: up to 4 retries using 1s, 2s, 5s, 10s unless provider `Retry-After` gives a safer delay;
- 503: up to 4 retries using 1s, 2s, 5s, 10s;
- 500/502/504: up to 2 retries using 1s, 3s;
- timeout/network error: up to 2 retries using 1s, 3s.

Every retry remains recorded as an error event. A model that succeeds after retry is `UNSTABLE`, not `ACTIVE`.

## 8. AIPerf eligibility

The existing `baseline-v1` text-generation profile is only valid for text-generation/chat-like models whose adapter declares AIPerf compatibility.

- `CHAT_TEXT`: eligible for `baseline-v1`.
- `VISION/MULTIMODAL`: not benchmarked by `baseline-v1` unless a future multimodal profile is explicitly implemented.
- `EMBEDDING`: not benchmarked by text-generation `baseline-v1`; smoke/stability may still establish availability.
- parser/translation/safety/rerank/special: benchmark only when a matching benchmark profile exists.

A supported model that passes smoke but has no benchmark profile is not failed. It receives a supported status plus a benchmark-stage outcome such as `SKIPPED_UNSUPPORTED_PROFILE`.

Performance comparisons must only compare compatible capability/profile pairs.

## 9. Accurate progress tracking

Add a `run_model_progress` table with one row per model selected at run start.

Minimum fields:

- `run_id`
- `model_db_id`
- `capability`
- `stage`
- `outcome`
- `started_at`
- `finished_at`
- `attempt_count`
- optional short diagnostic code

Stages:

- `PENDING`
- `CAPABILITY`
- `SMOKE`
- `STABILITY`
- `BENCHMARK`
- `DONE`

The progress denominator is the number of run-model rows, not the number of benchmark results. `processed` is the count in `DONE`.

The service emits progress events through an optional callback and persists progress before/after each stage so another process can inspect a live run safely.

CLI output for interactive runs should resemble:

```
[37/82] 45.1%  nvidia/model-id
Capability: CHAT_TEXT
Smoke: PASS
Stability: PASS
AIPerf: RUNNING
```

On completion it prints an outcome summary by model status and benchmark stage.

## 10. REST and MCP progress

Add REST:

- `GET /api/v1/runs/{run_id}/progress`

Return at least total, processed, current model/stage when available, counts by final status/outcome, and percent complete.

Add MCP tool:

- `benchmark_run_progress`

No raw credential or raw provider request is exposed.

Existing run status/results endpoints remain compatible.

## 11. Data migration

SQLite migration must be additive and safe for the existing v0.1 database.

- add capability columns to `models` with defaults;
- create `run_model_progress` if absent;
- do not rewrite existing benchmark/error/history rows;
- old status strings remain readable;
- new runs can transition old records to new statuses.

Migration is tested against a database created with the v0.1 schema.

## 12. Sanitization

Provider error text is useful for classification but should not persist unnecessary account/function identifiers.

Before writing `provider_message`:

- redact the active API key and authorization tokens;
- redact account identifiers from known provider patterns;
- replace UUID-like function/request identifiers with stable placeholders where they are not required for classification;
- cap message length;
- preserve HTTP status, normalized error type, and non-sensitive semantic text.

The sanitized message is what REST/MCP/export return.

## 13. Architecture changes

Introduce focused modules rather than expanding `service.py` indefinitely:

- `capabilities.py` — capability enum/detection rules;
- `classification.py` — error/status mapping and retry policy;
- `response_extract.py` — safe output extraction helpers;
- `progress.py` — progress domain object/query formatting;
- provider adapter methods for capability-specific probes;
- database migration/query methods for capability and run progress.

`BenchmarkService` remains the orchestrator but delegates detection, classification, extraction, and retry policy.

## 14. Testing

TDD coverage must include:

- migration from v0.1 schema;
- 404 invocation -> `NOT_AVAILABLE`, no retry;
- parser text-input 400 -> `INCOMPATIBLE`, no retry;
- embedding detection and `/embeddings` smoke path;
- unknown/special capability -> safe `UNSUPPORTED` rather than false `FAILED`;
- GLM-style alternate output field parsing so a valid response is not `EMPTY_RESPONSE`;
- retry counts for 429/503/500/timeout;
- success-after-retry -> `UNSTABLE`;
- exact progress denominator/processed count independent of benchmark result count;
- CLI progress emission;
- REST progress endpoint;
- MCP progress tool;
- message sanitization for secrets/account IDs/UUIDs;
- end-to-end mixed catalog fixture with chat, embedding, unavailable, unstable, and unsupported models.

No live provider calls are required for unit/integration tests. A later explicit NVIDIA verification run is a separate test step and must avoid production routing changes.

## 15. Acceptance criteria

v0.2 is accepted when:

1. a full mixed-provider run reports exact processed/total progress;
2. a discovered-but-not-callable 404 model becomes `NOT_AVAILABLE`, not `FAILED`;
3. an embedding model is not tested through chat completion;
4. a known unsupported special capability is retained as `UNSUPPORTED`, not discarded;
5. supported alternate text response shapes prevent false `EMPTY_RESPONSE` failures;
6. retry behavior is error-specific and bounded;
7. text AIPerf runs only for eligible capabilities/profiles;
8. CLI, REST, and MCP expose safe live progress;
9. provider messages are sanitized before persistence;
10. all existing v0.1 tests plus new v0.2 tests pass;
11. existing SQLite data remains readable without destructive migration;
12. production Hermes routing is untouched.
