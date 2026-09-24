# LLM Benchmark Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone Python package that discovers, tests and benchmarks LLM provider models and exposes one core through CLI, REST and MCP.

**Architecture:** Hexagonal-ish application core with provider, credential, repository and benchmark ports. SQLite and AIPerf are adapters. CLI/FastAPI/FastMCP call the same `BenchmarkService`; no interface owns benchmark logic.

**Tech Stack:** Python >=3.11, httpx, pydantic v2, FastAPI, uvicorn, FastMCP v4, SQLite, pytest, AIPerf subprocess integration.

**Spec:** `docs/superpowers/specs/2026-09-24-llm-benchmark-manager-design.md`

## Global Constraints
- Python >= 3.11.
- Primary install is pipx; Docker is optional.
- SQLite v1 backend.
- Raw secrets never persist or cross API/MCP boundaries.
- All production behavior follows RED -> GREEN TDD.
- Provider temporary failures do not delete models.
- No production routing mutation.

## Review Focus
- Provider base URL with/without `/v1` must not create malformed discovery URLs; Task 3 tests both.
- Missing ENV secret must fail without printing the value; Task 2 tests it.
- 429/503/timeouts must classify retryable rather than permanent; Task 3 tests normalization.
- AIPerf report with partial/error requests must persist both metrics and errors; Task 5 tests it.
- Concurrent/cancelled jobs must end in valid terminal states without corrupting SQLite; Task 6 tests it.

---

### Task 1: Package foundation, domain types, and SQLite schema
**Files:** Create `pyproject.toml`, `src/llmbench/__init__.py`, `src/llmbench/domain.py`, `src/llmbench/db.py`; Test `tests/test_db.py`, `tests/test_domain.py`.
**Interfaces:** Produces enums `ModelStatus`, `RunStatus`, dataclasses/models `Provider`, `ModelRecord`, `BenchmarkRun`, and `Database`.
- [ ] Write tests for enum values, schema creation, provider insert/list/get and model upsert preserving first_seen.
- [ ] Run focused tests and verify RED due missing package/types.
- [ ] Implement minimal domain types and SQLite repository with parameterized SQL and migrations-on-open.
- [ ] Run focused tests then full `pytest -q`; expect green.
- [ ] Commit `feat: add domain model and sqlite foundation`.

### Task 2: ENV credential resolver and redaction
**Files:** Create `src/llmbench/credentials.py`; Test `tests/test_credentials.py`.
**Interfaces:** Produces `EnvCredentialResolver.resolve(ref)->str`, `availability(ref)->bool`, and `redact_mapping`.
- [ ] Tests: present env resolves, missing raises `CredentialUnavailable` naming only variable, redactor removes authorization/api-key/token values.
- [ ] Run RED.
- [ ] Implement minimum resolver/redactor.
- [ ] Run focused and full tests green.
- [ ] Commit `feat: add environment credential resolver`.

### Task 3: OpenAI-compatible provider adapter
**Files:** Create `src/llmbench/providers/base.py`, `src/llmbench/providers/openai_compatible.py`, package init; Test `tests/test_provider_openai.py`.
**Interfaces:** Produces `ProviderAdapter` protocol, `DiscoveredModel`, `SmokeResult`, `normalize_error`, `OpenAICompatibleProvider.discover_models/smoke_test`.
- [ ] Tests with `httpx.MockTransport`: URL normalization for base with/without `/v1`, model-list parsing, bearer header set at request time, 401 auth, 429 rate-limit, 503 overloaded, timeout/retry classification, empty response.
- [ ] Run RED.
- [ ] Implement adapter with injected `httpx.AsyncClient`, bounded timeout, no secret logging.
- [ ] Run focused/full tests green.
- [ ] Commit `feat: add openai compatible provider adapter`.

### Task 4: Discovery reconciliation and status history
**Files:** Create `src/llmbench/discovery.py`; extend `db.py`; Test `tests/test_discovery.py`.
**Interfaces:** Produces `DiscoveryService.reconcile(provider_id, discovered_ids)` returning new/seen/missing sets.
- [ ] Tests: first discovery creates NEW; second preserves ACTIVE; absent prior becomes MISSING; reappearing MISSING becomes NEW without deleting history; DISABLED stays disabled.
- [ ] RED, implement, focused/full GREEN.
- [ ] Commit `feat: reconcile discovered model inventory`.

### Task 5: AIPerf runner and report parser
**Files:** Create `src/llmbench/benchmark/profiles.py`, `aiperf.py`, package init; Test `tests/test_aiperf.py`, fixtures under `tests/fixtures/`.
**Interfaces:** Produces `BenchmarkProfile`, `AIPerfRunner.build_command/run`, `parse_aiperf_report`. Raw credential is supplied only through child `env`, never argv.
- [ ] Tests: deterministic baseline-v1 args; secret absent from argv; report parser normalizes TTFT/latency/tok-s/error-rate; partial 503 report returns metrics plus normalized errors; missing executable gives explicit unavailable error.
- [ ] RED, implement subprocess runner using temp config with restrictive permissions and sanitized output, focused/full GREEN.
- [ ] Commit `feat: add aiperf benchmark adapter`.

### Task 6: Benchmark orchestration and local job manager
**Files:** Create `src/llmbench/service.py`, `src/llmbench/jobs.py`; extend `db.py`; Test `tests/test_service.py`, `tests/test_jobs.py`.
**Interfaces:** Produces `BenchmarkService.add_provider/discover/run_provider/results/history`, `LocalJobManager.submit/status/cancel`.
- [ ] Tests: NEW -> smoke -> benchmark -> ACTIVE; retryable errors -> UNSTABLE not FAILED; permanent errors -> FAILED/UNSUPPORTED; run/result/error persistence append-only; run modes full/new/active/unstable; cancellation terminal state.
- [ ] RED, implement minimal orchestration and ThreadPool/local async job manager, focused/full GREEN.
- [ ] Commit `feat: orchestrate discovery benchmark jobs`.

### Task 7: CLI interactive and automation commands
**Files:** Create `src/llmbench/cli.py`, `src/llmbench/runtime.py`; Test `tests/test_cli.py`.
**Interfaces:** Console entry point `llmbench=llmbench.cli:main`.
- [ ] Tests: no args shows interactive menu; provider add/list/discover; run modes; results/history; secret input is ENV-name only, never raw secret persistence.
- [ ] RED, implement argparse-based CLI and menu using same service factory, focused/full GREEN.
- [ ] Commit `feat: add interactive and automation cli`.

### Task 8: REST API and local API job semantics
**Files:** Create `src/llmbench/api.py`; Test `tests/test_api.py`.
**Interfaces:** Produces `create_app(service, jobs)->FastAPI` with `/api/v1` endpoints in the spec.
- [ ] Tests using TestClient for provider CRUD subset, discovery, run start/status/cancel/results, model history, input validation, and proof responses expose `credential_available/ref` but no value.
- [ ] RED, implement routes calling only service/jobs, focused/full GREEN.
- [ ] Commit `feat: expose benchmark rest api`.

### Task 9: MCP surface
**Files:** Create `src/llmbench/mcp_server.py`; Test `tests/test_mcp.py`.
**Interfaces:** Produces `build_mcp_server(service, jobs)` and tool callables for provider/model/run operations.
- [ ] Tests call underlying registered tool functions/service facade and verify tool names, run start/status/results, unstable/new helpers, and absence of any raw-secret tool.
- [ ] RED, implement with FastMCP v4 and thin wrappers over same service/jobs, focused/full GREEN.
- [ ] Commit `feat: expose benchmark mcp tools`.

### Task 10: Export, Docker, documentation, packaging and end-to-end verification
**Files:** Create `src/llmbench/export.py`, `Dockerfile`, `docker/entrypoint.sh`, `README.md`, `LICENSE`; Test `tests/test_export.py`, `tests/test_integration.py`.
**Interfaces:** Produces JSON/CSV export and documented install/run workflows.
- [ ] Tests: deterministic CSV/JSON export, temporary SQLite end-to-end fake provider run, package import and CLI help.
- [ ] RED, implement exports/docs/container files.
- [ ] Build wheel/sdist, install wheel in clean temp venv, run `llmbench --help`, run full `pytest -q`, run compile check.
- [ ] Security scan repository for likely raw credential patterns and ensure test fixtures contain no real secrets.
- [ ] Commit `docs: package and document llm benchmark manager`.
