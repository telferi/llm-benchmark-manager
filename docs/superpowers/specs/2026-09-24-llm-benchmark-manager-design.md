# LLM Benchmark Manager Design Specification

**Date:** 2026-09-24

## Goal
Build a standalone, provider-agnostic LLM discovery and benchmarking application installable by anyone. It exposes the same core through an interactive/non-interactive CLI, REST API, and MCP server. Hermes is only an optional client.

## Global constraints
- Python >= 3.11.
- Primary install: `pipx install llm-benchmark-manager`; optional Docker image.
- SQLite is the v1 persistence backend.
- AIPerf is the performance benchmark backend; the application must also work for discovery/smoke/stability when AIPerf is not installed.
- Raw provider credentials are never stored in SQLite, logs, artifacts, REST responses, MCP responses, or process arguments.
- Primary credential source is an environment variable reference such as `NVIDIA_API_KEY`.
- Benchmark history is append-only: reruns never overwrite prior run/results.
- Temporary provider errors (429, 500, 502, 503, 504, timeout/reset) are classified separately from permanent model failures.
- The benchmark manager never changes production routing.

## User flow
`llmbench` opens a menu offering: add provider, choose existing provider, retest all providers, view results, settings, exit. Existing provider actions include full retest, active-only, unstable/failed, refresh model list + test NEW models, one-model test, and history.

## Providers and model discovery
The first adapter is `OpenAICompatibleProvider`. It normalizes base URLs and discovers models from `/v1/models` or `/models`. Provider-specific behavior lives in adapters, not the core. Discovery reconciles current model IDs with the database and assigns `NEW`, `ACTIVE`, `UNSTABLE`, `FAILED`, `UNSUPPORTED`, `DISABLED`, or `MISSING`. Missing models remain in history.

## Test pipeline
Discovery -> endpoint/auth check -> single-request smoke -> small stability test -> AIPerf baseline -> classification -> database. Expensive benchmark stages only run for models that pass earlier stages. Retryable failures use bounded exponential backoff (default 1s, 2s, 5s, 10s).

## Credential model
Interactive provider onboarding asks only for endpoint URL and a hidden API key. Provider name/slug is derived automatically from the endpoint hostname. The raw key is never written to SQLite. The credential layer first attempts an operating-system keyring and falls back on headless systems to a Fernet-encrypted local vault whose files are protected with user-only permissions. Provider records persist only `credential_source` plus an opaque `credential_ref`. Environment-variable references remain supported for automation, containers, systemd and agent deployments. API/MCP may expose whether a credential is available but never its raw value.

## Persistence
SQLite tables: providers, models, benchmark_runs, benchmark_results, errors, model_status_history. Runs have statuses `QUEUED`, `RUNNING`, `COMPLETED`, `COMPLETED_WITH_ERRORS`, `FAILED`, `CANCELLED`. Store AIPerf version, profile version, effective parameters, normalized metrics, errors, timestamps and artifact paths.

## Benchmark profiles
Versioned profiles include `baseline-v1`, `stability-v1`, `throughput-v1`, and later `reasoning-v1`. Provider/model overrides are explicit and persisted with the result.

## CLI
Commands include provider add/list/discover, run provider (`full`, `new`, `active`, `unstable`), run all, model test/history, results, `serve`, and `mcp`. Interactive mode is the default when no subcommand is supplied. Interactive new-provider onboarding asks only for endpoint URL and hidden API key; the explicit `provider add --credential-env ...` form remains available for automation.

## REST API
Prefix `/api/v1`. Minimum endpoints: providers list/create/get, provider discovery/models, runs create/get/cancel/results, model get/history. Long-running runs return a `run_id` and execute through a local job manager in v1; Redis/Celery are not required.

## MCP
Expose safe tools backed by the same application service: provider list/get/discover, model list/get/history, run start/status/cancel/results, retest unstable, test new models. No raw-secret tool exists.

## Packaging and dependencies
Use `pyproject.toml` with a console script named `llmbench`. Runtime stack: stdlib + httpx + pydantic, FastAPI/uvicorn for REST, FastMCP v4 for MCP. Tests use pytest. Docker is optional and invokes the same package entry point.

## Security
Redact authorization-like values, validate provider URLs, parameterize SQLite operations, validate subprocess arguments, use bounded timeouts, isolate artifact directories, and never pass a raw secret on a command line. Environment values are inherited into the AIPerf child process only.

## V1 acceptance criteria
On a clean Linux system a user can install with pipx, register an OpenAI-compatible provider using an ENV credential reference, discover/reconcile models, smoke/stability-test them, benchmark passing models with AIPerf, persist complete history, rerun an existing provider, detect NEW/MISSING models, use the CLI/REST/MCP surfaces, export results to JSON/CSV, and do all of this without raw credential disclosure.
