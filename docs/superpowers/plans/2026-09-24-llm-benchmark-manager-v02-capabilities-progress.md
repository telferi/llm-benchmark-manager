# LLM Benchmark Manager v0.2 Capability-Aware Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make full-catalog runs capability-aware, correctly classify unavailable/incompatible models, expose exact live progress, and preserve safe historical results without breaking the v0.1 database.

**Architecture:** Keep `BenchmarkService` as orchestrator, but move capability detection, output extraction, classification/retry policy, and progress formatting into focused modules. Extend SQLite additively with model capability columns and a `run_model_progress` table; provider adapters expose capability-specific probes; CLI/REST/MCP consume one persisted progress query. Existing credential handling, history, run/result APIs, and AIPerf adapter stay compatible.

**Tech Stack:** Python 3.11+, SQLite, httpx, FastAPI, FastMCP, pytest, NVIDIA AIPerf 0.12.0.

**Spec:** `docs/superpowers/specs/2026-09-24-llm-benchmark-manager-v02-capabilities-progress-design.md`

## Global Constraints

- Existing v0.1 SQLite data must remain readable; migration is additive and non-destructive.
- `FAILED` is reserved for definitive failure under the correct supported capability path.
- Invocation 404 becomes `NOT_AVAILABLE`, never `FAILED`.
- Recognized capability mismatch 400 becomes `INCOMPATIBLE`, never `FAILED`.
- Retry policy is error-specific: 429/503 => 1,2,5,10s; 500/502/504 and timeout/network => 1,3s; deterministic 4xx/auth/capability mismatch => no retry.
- `baseline-v1` AIPerf is only eligible for `CHAT_TEXT` in v0.2.
- Provider secrets and unnecessary provider/account identifiers must not enter SQLite, logs, API/MCP responses, exports, or argv.
- CLI, REST, and MCP progress must derive from the same persisted `run_model_progress` data.
- No live provider call is required by unit/integration tests.
- Production Hermes routing must not be modified.

## Review Focus

- Existing v0.1 databases with old `FAILED` rows must migrate without rewrite or data loss; new runs may transition them normally.
- Discovery metadata can be sparse or malformed; capability detection must fall back conservatively to model-id heuristics or `UNKNOWN` rather than crashing.
- A valid chat response with structured content or reasoning text must not be misclassified as `EMPTY_RESPONSE`.
- A run with zero benchmark-eligible models must still reach `COMPLETED`/`COMPLETED_WITH_ERRORS` with 100% progress.
- Sanitization must remove credentials, account-like identifiers, UUID/function IDs, and cap message length without destroying the semantic error class.

---

## File Structure

New focused modules:

- `src/llmbench/capabilities.py` — capability enum, detection result, metadata/id/error hint detection.
- `src/llmbench/classification.py` — normalized error classes, model-status mapping, retry schedules, capability-mismatch detection.
- `src/llmbench/response_extract.py` — tolerant chat/output extraction.
- `src/llmbench/progress.py` — progress dataclass and summary formatting.

Existing files to modify:

- `src/llmbench/domain.py` — new statuses and capability fields on `ModelRecord`.
- `src/llmbench/db.py` — additive migration, capability persistence, progress rows/query/update methods.
- `src/llmbench/providers/base.py` — capability probe interface contract.
- `src/llmbench/providers/openai_compatible.py` — chat and embedding probes using shared extraction/classification.
- `src/llmbench/service.py` — stage orchestration, capability routing, retry policy, benchmark eligibility, progress callback.
- `src/llmbench/cli.py` — interactive live progress and final summary.
- `src/llmbench/api.py` — run progress endpoint.
- `src/llmbench/mcp_server.py` — run progress tool.
- `src/llmbench/credentials.py` — provider-message sanitizer helper if shared redaction belongs here.
- `README.md` — v0.2 statuses, capability behavior, progress surface.

---

### Task 1: Additive data model and migration

**Files:**
- Modify: `src/llmbench/domain.py`
- Modify: `src/llmbench/db.py`
- Modify: `tests/test_db.py`
- Create: `tests/test_migration_v01.py`
- Create: `tests/test_progress_db.py`

**Interfaces:**
- Produces: `ModelCapability`, `ModelRecord.capability`, `ModelRecord.capability_source`, `ModelRecord.capability_confidence`.
- Produces: `Database.set_model_capability(model_db_id, capability, source, confidence)`.
- Produces: `Database.init_run_progress(run_id, models)`, `Database.update_run_progress(...)`, `Database.get_run_progress(run_id)`.
- Consumed by Tasks 2, 5, 6, 7.

- [ ] **Step 1: Write failing status/capability model tests**

```python
from llmbench.domain import ModelStatus, ModelCapability


def test_v02_statuses_and_capabilities_exist():
    assert ModelStatus.NOT_AVAILABLE.value == "NOT_AVAILABLE"
    assert ModelStatus.INCOMPATIBLE.value == "INCOMPATIBLE"
    assert ModelCapability.CHAT_TEXT.value == "CHAT_TEXT"
    assert ModelCapability.EMBEDDING.value == "EMBEDDING"
    assert ModelCapability.UNKNOWN.value == "UNKNOWN"
```

- [ ] **Step 2: Write failing v0.1 migration test**

Create a temporary SQLite file manually with the v0.1 `models` and `benchmark_runs` schema, insert one `FAILED` model and one historical run, then instantiate `Database(path)` and assert:

```python
m = db.get_model(provider_id, "legacy/model")
assert m.status == ModelStatus.FAILED
assert m.capability == ModelCapability.UNKNOWN
assert m.capability_source == "unknown"
assert db.get_run("run_legacy").id == "run_legacy"
```

Also assert the original benchmark/history row counts are unchanged.

- [ ] **Step 3: Run RED tests**

Run:
```bash
pytest -q tests/test_db.py tests/test_migration_v01.py tests/test_progress_db.py
```
Expected: FAIL because new enums/columns/progress methods do not exist.

- [ ] **Step 4: Implement additive schema migration**

Extend `ModelStatus` and add:

```python
class ModelCapability(str, Enum):
    CHAT_TEXT="CHAT_TEXT"
    EMBEDDING="EMBEDDING"
    VISION="VISION"
    MULTIMODAL="MULTIMODAL"
    PARSER="PARSER"
    TRANSLATION="TRANSLATION"
    SAFETY="SAFETY"
    RERANK="RERANK"
    SPECIAL="SPECIAL"
    UNKNOWN="UNKNOWN"
```

Add `capability`, `capability_source`, and `capability_confidence` to `ModelRecord` with DB defaults `UNKNOWN`, `unknown`, and `0.0`.

In `_migrate()`, inspect `PRAGMA table_info(models)` and issue only missing-column `ALTER TABLE` statements. Create:

```sql
CREATE TABLE IF NOT EXISTS run_model_progress(
  run_id TEXT NOT NULL REFERENCES benchmark_runs(id) ON DELETE CASCADE,
  model_db_id INTEGER NOT NULL REFERENCES models(id),
  capability TEXT NOT NULL DEFAULT 'UNKNOWN',
  stage TEXT NOT NULL DEFAULT 'PENDING',
  outcome TEXT,
  started_at TEXT,
  finished_at TEXT,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  diagnostic_code TEXT,
  PRIMARY KEY(run_id, model_db_id)
);
```

- [ ] **Step 5: Implement progress DB methods**

Use exact signatures:

```python
def init_run_progress(self, run_id: str, models: list[ModelRecord]) -> None: ...
def update_run_progress(self, run_id: str, model_db_id: int, *, stage: str,
                        capability: ModelCapability | None = None,
                        outcome: str | None = None,
                        attempt_increment: int = 0,
                        diagnostic_code: str | None = None,
                        finished: bool = False) -> None: ...
def get_run_progress(self, run_id: str) -> dict: ...
```

`get_run_progress()` returns:

```python
{
  "run_id": run_id,
  "total": 5,
  "processed": 2,
  "percent": 40.0,
  "current": {"model_id": "...", "stage": "SMOKE", "capability": "CHAT_TEXT"} | None,
  "by_outcome": {"ACTIVE": 1, "NOT_AVAILABLE": 1},
  "models": [...]
}
```

`processed` counts `stage='DONE'`, never benchmark result rows.

- [ ] **Step 6: Run GREEN tests**

Run:
```bash
pytest -q tests/test_db.py tests/test_migration_v01.py tests/test_progress_db.py
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/llmbench/domain.py src/llmbench/db.py tests/test_db.py tests/test_migration_v01.py tests/test_progress_db.py
git commit -m "feat: add v02 capability and progress schema"
```

---

### Task 2: Capability detection

**Files:**
- Create: `src/llmbench/capabilities.py`
- Create: `tests/test_capabilities.py`

**Interfaces:**
- Consumes: `ModelCapability` from Task 1.
- Produces: `CapabilityDetection` and `detect_capability(model_id, metadata) -> CapabilityDetection`.
- Produces: `refine_capability_from_error(current, message) -> CapabilityDetection | None`.
- Consumed by Tasks 4 and 5.

- [ ] **Step 1: Write failing detection tests**

Cover metadata precedence, conservative id heuristics, malformed metadata, and unknown fallback:

```python
assert detect_capability("nvidia/nemotron-3-embed-1b", {}).capability is ModelCapability.EMBEDDING
assert detect_capability("nvidia/nemotron-parse", {}).capability is ModelCapability.PARSER
assert detect_capability("nvidia/riva-translate-4b", {}).capability is ModelCapability.TRANSLATION
assert detect_capability("meta/llama-guard-4-12b", {}).capability is ModelCapability.SAFETY
assert detect_capability("vendor/model-x", {}).capability is ModelCapability.UNKNOWN
```

A metadata declaration such as `{"task":"text-generation"}` must override a misleading model-id heuristic and yield `CHAT_TEXT` with source `metadata`.

- [ ] **Step 2: Run RED test**

Run:
```bash
pytest -q tests/test_capabilities.py
```
Expected: FAIL because module does not exist.

- [ ] **Step 3: Implement detector**

Use:

```python
@dataclass(frozen=True)
class CapabilityDetection:
    capability: ModelCapability
    source: str
    confidence: float
```

Precedence must be metadata -> adapter-provided metadata keys -> model-id heuristic -> `UNKNOWN`. Heuristics only inspect lowercased tokens and never change model status.

- [ ] **Step 4: Add error-feedback refinement tests and implementation**

Recognize semantic phrases such as `does not support text input` and return a non-chat detection hint without asserting a specific capability unless the message gives one. Generic errors return `None`.

- [ ] **Step 5: Run GREEN tests and full related suite**

Run:
```bash
pytest -q tests/test_capabilities.py tests/test_discovery.py tests/test_domain.py
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/llmbench/capabilities.py tests/test_capabilities.py
git commit -m "feat: detect model capabilities conservatively"
```

---

### Task 3: Response extraction, classification, retry policy, and sanitization

**Files:**
- Create: `src/llmbench/response_extract.py`
- Create: `src/llmbench/classification.py`
- Modify: `src/llmbench/credentials.py`
- Create: `tests/test_response_extract.py`
- Create: `tests/test_classification.py`
- Modify: `tests/test_credentials.py`

**Interfaces:**
- Produces: `extract_text_response(payload: dict) -> str | None`.
- Produces: `classify_http_error(status_code, message) -> ErrorClassification`.
- Produces: `retry_delays_for(error_type: str) -> tuple[int, ...]`.
- Produces: `sanitize_provider_message(text, secrets=()) -> str`.
- Consumed by Tasks 4 and 5.

- [ ] **Step 1: Write failing response extraction tests**

Cover these exact valid shapes:

```python
{"choices":[{"message":{"content":"hello"}}]}
{"choices":[{"message":{"content":[{"type":"text","text":"hello"}]}}]}
{"choices":[{"message":{"reasoning_content":"hello"}}]}
{"choices":[{"text":"hello"}]}
{"output_text":"hello"}
```

Also assert usage-only/null/empty/`[DONE]` payloads return `None`.

- [ ] **Step 2: Write failing classification/retry tests**

Assert:

```python
assert classify_http_error(404, "not found").model_status == ModelStatus.NOT_AVAILABLE
assert retry_delays_for("MODEL_NOT_FOUND") == ()
assert retry_delays_for("RATE_LIMITED") == (1,2,5,10)
assert retry_delays_for("OVERLOADED") == (1,2,5,10)
assert retry_delays_for("PROVIDER_ERROR") == (1,3)
assert retry_delays_for("TIMEOUT") == (1,3)
```

Recognized 400 capability mismatch text must classify `INCOMPATIBLE` with zero retry.

- [ ] **Step 3: Write failing sanitization tests**

Input contains a fake secret, Bearer token, UUID, NVIDIA-like account identifier, and >2000 characters. Assert output:

```python
assert "fake-secret" not in sanitized
assert "Bearer" not in sanitized
assert "123e4567-e89b-12d3-a456-426614174000" not in sanitized
assert "<uuid>" in sanitized
assert len(sanitized) <= 512
```

- [ ] **Step 4: Run RED tests**

Run:
```bash
pytest -q tests/test_response_extract.py tests/test_classification.py tests/test_credentials.py
```
Expected: FAIL on missing modules/functions.

- [ ] **Step 5: Implement minimal shared helpers**

`ErrorClassification` fields:

```python
@dataclass(frozen=True)
class ErrorClassification:
    error_type: str
    retryable: bool
    model_status: ModelStatus | None
    diagnostic_code: str
```

401/403 return `model_status=None` because they are provider/run credential problems, not model health.

- [ ] **Step 6: Run GREEN tests**

Run:
```bash
pytest -q tests/test_response_extract.py tests/test_classification.py tests/test_credentials.py
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/llmbench/response_extract.py src/llmbench/classification.py src/llmbench/credentials.py tests/test_response_extract.py tests/test_classification.py tests/test_credentials.py
git commit -m "feat: add response classification retry and sanitization helpers"
```

---

### Task 4: Capability-specific OpenAI-compatible probes

**Files:**
- Modify: `src/llmbench/providers/base.py`
- Modify: `src/llmbench/providers/openai_compatible.py`
- Modify: `tests/test_provider_openai.py`

**Interfaces:**
- Consumes: capability detection/extraction/classification from Tasks 2-3.
- Produces: `probe(model_id, api_key, capability) -> SmokeResult`.
- Produces: `benchmark_profile_for(capability) -> str | None`.
- Consumed by Task 5.

- [ ] **Step 1: Write failing chat alternate-output test**

Use `httpx.MockTransport` returning a GLM-style/alternate valid field, and assert `probe(..., CHAT_TEXT).ok is True` rather than `EMPTY_RESPONSE`.

- [ ] **Step 2: Write failing embedding-path test**

Capture request URL/body and assert an `EMBEDDING` model uses `/v1/embeddings`, never `/v1/chat/completions`, with a tiny text input. Validate at least one non-empty numeric vector.

- [ ] **Step 3: Write failing unsupported-special test**

For `PARSER`, `TRANSLATION`, `SAFETY`, `RERANK`, `SPECIAL`, and `VISION/MULTIMODAL` without an explicitly implemented adapter format, assert the provider returns a non-retryable `UNSUPPORTED` result without performing HTTP.

- [ ] **Step 4: Run RED tests**

Run:
```bash
pytest -q tests/test_provider_openai.py
```
Expected: FAIL because `probe` and benchmark eligibility do not exist.

- [ ] **Step 5: Implement provider probe routing**

Exact contract:

```python
def probe(self, model_id: str, api_key: str, capability: ModelCapability) -> SmokeResult: ...
def benchmark_profile_for(self, capability: ModelCapability) -> str | None:
    return "baseline-v1" if capability is ModelCapability.CHAT_TEXT else None
```

Keep `smoke_test()` as a backward-compatible wrapper that calls `probe(..., CHAT_TEXT)` so old tests/clients do not break.

- [ ] **Step 6: Run GREEN and legacy provider tests**

Run:
```bash
pytest -q tests/test_provider_openai.py tests/test_integration.py
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/llmbench/providers/base.py src/llmbench/providers/openai_compatible.py tests/test_provider_openai.py
git commit -m "feat: route probes by model capability"
```

---

### Task 5: Orchestrate capability-aware runs and exact progress

**Files:**
- Modify: `src/llmbench/service.py`
- Create: `src/llmbench/progress.py`
- Modify: `tests/test_service.py`
- Create: `tests/test_progress_service.py`
- Create: `tests/test_mixed_catalog.py`

**Interfaces:**
- Consumes: all Tasks 1-4 interfaces.
- Produces: `BenchmarkService.execute_run(..., progress_callback=None)` persisted stage machine.
- Produces: `BenchmarkService.run_progress(run_id) -> dict`.
- Consumed by Tasks 6-7.

- [ ] **Step 1: Write failing 404 classification test**

A discovered chat model whose provider probe returns HTTP 404 `MODEL_NOT_FOUND` must finish `NOT_AVAILABLE`, have exactly one attempt, no retry sleeps, no AIPerf call, and a `DONE` progress row.

- [ ] **Step 2: Write failing capability mismatch test**

A model initially `UNKNOWN` whose probe returns recognized 400 text-input mismatch must become `INCOMPATIBLE`, have no identical retry, and persist a refined capability/source hint when available.

- [ ] **Step 3: Write failing retry schedule tests**

Parameterize 429, 503, 500, timeout. Capture sleep values and assert exact schedules from Task 3. If the final attempt succeeds, model must be `UNSTABLE`.

- [ ] **Step 4: Write failing AIPerf eligibility test**

A passing `EMBEDDING` model must not call AIPerf `baseline-v1`; it must finish `ACTIVE` with progress outcome `SKIPPED_UNSUPPORTED_PROFILE`. A passing `CHAT_TEXT` model must call AIPerf.

- [ ] **Step 5: Write failing progress denominator/callback test**

For five selected models with only one benchmark result, assert:

```python
progress = svc.run_progress(run.id)
assert progress["total"] == 5
assert progress["processed"] == 5
assert progress["percent"] == 100.0
```

Capture callback events and assert stage order per model includes `CAPABILITY`, `SMOKE`, optionally `STABILITY`/`BENCHMARK`, then `DONE`.

- [ ] **Step 6: Write failing mixed-catalog end-to-end fixture**

Fixture contains:
- one healthy chat model -> `ACTIVE` + AIPerf;
- one embedding model -> `ACTIVE` + no text AIPerf;
- one 404 model -> `NOT_AVAILABLE`;
- one success-after-503 model -> `UNSTABLE`;
- one parser/special model -> `UNSUPPORTED` or `INCOMPATIBLE` according to detector/probe evidence.

Assert total/processed is exact and no unsupported model becomes `FAILED`.

- [ ] **Step 7: Run RED service tests**

Run:
```bash
pytest -q tests/test_service.py tests/test_progress_service.py tests/test_mixed_catalog.py
```
Expected: FAIL on old orchestration.

- [ ] **Step 8: Implement stage orchestration**

At run start call `init_run_progress()` with the selected models. Before each stage persist progress, increment attempts around probe calls, and emit a callback snapshot after persistence. Use capability detector before probe. Delegate retry schedule to `classification.retry_delays_for()`.

Status rules:
- non-retryable 404 -> `NOT_AVAILABLE`;
- capability mismatch -> `INCOMPATIBLE`;
- known unsupported path -> `UNSUPPORTED`;
- transient eventually successful -> `UNSTABLE`;
- supported definitive non-transient failure -> `FAILED`;
- successful supported probe + no eligible benchmark profile -> `ACTIVE` with skipped benchmark outcome;
- successful eligible benchmark with no transient/errors -> `ACTIVE`.

- [ ] **Step 9: Run GREEN service and full core suite**

Run:
```bash
pytest -q tests/test_service.py tests/test_progress_service.py tests/test_mixed_catalog.py tests/test_aiperf.py tests/test_discovery.py
```
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add src/llmbench/service.py src/llmbench/progress.py tests/test_service.py tests/test_progress_service.py tests/test_mixed_catalog.py
git commit -m "feat: orchestrate capability-aware benchmark runs"
```

---

### Task 6: Interactive CLI progress and summary

**Files:**
- Modify: `src/llmbench/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `BenchmarkService.execute_run(..., progress_callback=...)` and `run_progress()` from Task 5.
- Produces: human-readable live progress and final status summary.

- [ ] **Step 1: Write failing CLI progress test**

Inject a fake service callback sequence and assert output contains:

```text
[2/5] 40.0%  vendor/model-b
Capability: CHAT_TEXT
Smoke: PASS
```

The API key must never appear in captured stdout/stderr.

- [ ] **Step 2: Write failing completion summary test**

Assert final output contains counts for `ACTIVE`, `UNSTABLE`, `NOT_AVAILABLE`, `INCOMPATIBLE`, `UNSUPPORTED`, `FAILED`, and `Total processed`.

- [ ] **Step 3: Run RED CLI tests**

Run:
```bash
pytest -q tests/test_cli.py
```
Expected: FAIL because interactive execution does not pass a progress callback.

- [ ] **Step 4: Implement compact progress renderer**

Add focused helpers:

```python
def _render_progress(snapshot: dict) -> None: ...
def _render_run_summary(snapshot: dict) -> None: ...
```

Do not clear the terminal or require curses; print stage transitions only so logs remain useful in SSH/systemd captures.

- [ ] **Step 5: Run GREEN CLI tests**

Run:
```bash
pytest -q tests/test_cli.py
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/llmbench/cli.py tests/test_cli.py
git commit -m "feat: show exact live benchmark progress in cli"
```

---

### Task 7: REST and MCP run progress

**Files:**
- Modify: `src/llmbench/api.py`
- Modify: `src/llmbench/mcp_server.py`
- Modify: `tests/test_api.py`
- Modify: `tests/test_mcp.py`

**Interfaces:**
- Consumes: `BenchmarkService.run_progress(run_id)`.
- Produces: `GET /api/v1/runs/{run_id}/progress`.
- Produces MCP tool: `benchmark_run_progress`.

- [ ] **Step 1: Write failing REST progress test**

Create a run with persisted progress and assert endpoint returns 200 plus exact `total`, `processed`, `percent`, `current`, and `by_outcome`. Unknown run returns 404 without traceback leakage.

- [ ] **Step 2: Write failing MCP progress test**

Assert `benchmark_run_progress` exists in `MCP_TOOL_NAMES`, invokes the same service method, and returned text/data contains no credential values.

- [ ] **Step 3: Run RED interface tests**

Run:
```bash
pytest -q tests/test_api.py tests/test_mcp.py
```
Expected: FAIL because progress surfaces do not exist.

- [ ] **Step 4: Implement REST and MCP surfaces**

REST handler must only return persisted summary, never raw provider payloads. MCP function signature:

```python
def benchmark_run_progress(run_id: str) -> dict:
    return service.run_progress(run_id)
```

- [ ] **Step 5: Run GREEN interface tests**

Run:
```bash
pytest -q tests/test_api.py tests/test_mcp.py
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/llmbench/api.py src/llmbench/mcp_server.py tests/test_api.py tests/test_mcp.py
git commit -m "feat: expose benchmark progress over rest and mcp"
```

---

### Task 8: Regression, documentation, packaging, and release verification

**Files:**
- Modify: `README.md`
- Modify if needed: `pyproject.toml`
- Modify/add tests only for defects found by final review.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: verified distributable v0.2-capable branch ready for real NVIDIA retest.

- [ ] **Step 1: Update README**

Document:
- new statuses and their exact meaning;
- capability categories;
- exact progress semantics (`processed` = `DONE` rows);
- why 404 means `NOT_AVAILABLE`;
- capability-specific benchmark eligibility;
- REST progress endpoint and MCP progress tool;
- secure/sanitized errors.

- [ ] **Step 2: Run full pytest suite**

Run:
```bash
pytest -q
```
Expected: all tests PASS, including all v0.1 tests and new v0.2 tests.

- [ ] **Step 3: Compile and package**

Run:
```bash
python -m compileall -q src
rm -rf dist build
python -m build
```
Expected: wheel and sdist build successfully.

- [ ] **Step 4: Clean-wheel install smoke**

Create a fresh temporary venv, install `dist/*.whl`, then run:

```bash
llmbench --help
python -c "from llmbench.domain import ModelCapability, ModelStatus; print(ModelCapability.CHAT_TEXT, ModelStatus.NOT_AVAILABLE)"
```
Expected: both commands succeed.

- [ ] **Step 5: Security scan**

Search tracked source/tests/docs for provider-key-shaped fixtures and ensure no real credential/account identifiers from the NVIDIA report were copied into the repository. Assert provider sanitizer tests pass separately.

- [ ] **Step 6: Whole-branch code review**

Review the complete range from `1a0049f` to HEAD with focus on migration safety, classification correctness, secret leakage, progress consistency, and old API compatibility. Any Critical/Important finding gets exactly one RED->GREEN fix pass followed by full-suite rerun.

- [ ] **Step 7: Final verification**

Run:
```bash
pytest -q
python -m compileall -q src
git status --short
git log -1 --oneline
```
Expected: tests PASS, compile PASS, working tree clean.

- [ ] **Step 8: Commit documentation/release adjustments**

```bash
git add README.md pyproject.toml tests src
git commit -m "docs: finalize v02 capability-aware benchmark flow"
```

If no files changed after the last feature commit, do not create an empty commit; record that in the execution ledger instead.
