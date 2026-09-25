# LLM Benchmark Manager

[English](README.md) | [Magyar](README.hu.md)

LLM Benchmark Manager is a standalone, open-source tool for discovering models exposed by an LLM provider, validating that they can actually be called, classifying their capabilities and health, benchmarking compatible text-generation models with NVIDIA AIPerf, and preserving historical evidence in SQLite.

It is intentionally independent of any agent framework, operating-system user, host name, directory layout, or routing system. It can be used manually from a terminal, automated through a REST API, or controlled by an AI/agent through MCP.

## What it does

A normal full run performs the following pipeline:

1. discover the provider model catalog;
2. create a persistent progress row for every selected model;
3. detect or infer the model capability;
4. run a capability-aware smoke probe;
5. perform bounded stability checks and retry transient provider failures;
6. run AIPerf only when the model has a compatible benchmark profile;
7. classify the model (`ACTIVE`, `UNSTABLE`, `NOT_AVAILABLE`, etc.);
8. store metrics, normalized errors, progress and status history in SQLite.

The tool never deletes historical benchmark evidence when a model changes state later.

## Release status

Current release candidate: **0.3.0**.

The project is prepared for a future public GitHub/PyPI release, but publication is a separate step. From a source checkout or built wheel it is already installable with `pipx` or `pip`.

## Requirements

- Python 3.11+
- Internet/network access to the provider being tested
- Provider credentials for providers that require authentication

**NVIDIA AIPerf 0.12.0 is a required package dependency.** Installing LLM Benchmark Manager installs AIPerf automatically. You do not need to install AIPerf separately.

AIPerf is currently used by the built-in `CHAT_TEXT` baseline profile. Discovery, capability detection and non-text probes still use the same installed application even when no AIPerf benchmark is applicable to a particular model.

## Installation

### From a source checkout

Recommended for the current release candidate:

```bash
pipx install .
llmbench --help
```

For development:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest -q
```

### From a built wheel

```bash
pipx install dist/llm_benchmark_manager-0.3.0-py3-none-any.whl
llmbench --help
```

### Future PyPI installation

After the project is published to PyPI:

```bash
pipx install llm-benchmark-manager
```

### Docker

```bash
docker build -t llm-benchmark-manager:0.3.0 .
```

Example REST API mode:

```bash
docker run --rm \
  --env-file providers.env \
  -p 8765:8765 \
  -v llmbench-data:/data \
  llm-benchmark-manager:0.3.0 serve --host 0.0.0.0 --port 8765
```

The image stores application data under `/data`. AIPerf is installed automatically because it is a normal project dependency.

## Quick start

Run the interactive interface:

```bash
llmbench
```

For a new provider, enter only the provider endpoint URL and API key:

```text
New provider
Endpoint URL: https://provider.example.com
API key: ***************
```

The provider slug is derived from the endpoint hostname. If that normalized endpoint already exists, the existing provider record is reused rather than duplicated.

For an existing provider the interactive menu supports:

- full retest;
- `ACTIVE`-only retest;
- `UNSTABLE`/`FAILED` retest;
- refresh discovery and test only `NEW` models;
- test one model;
- list known models and states.

## Automation CLI

```bash
llmbench provider list
llmbench provider discover PROVIDER

llmbench run PROVIDER --mode full
llmbench run PROVIDER --mode new
llmbench run PROVIDER --mode active
llmbench run PROVIDER --mode unstable_failed
llmbench run --all --mode full

llmbench model test PROVIDER MODEL_ID
llmbench results RUN_ID
llmbench history PROVIDER MODEL_ID
llmbench export RUN_ID --format json --output run.json
llmbench export RUN_ID --format csv --output run.csv
```

`PROVIDER` can be the configured provider identifier/slug accepted by the service.

## Provider compatibility

The built-in generic adapter targets OpenAI-compatible provider APIs and uses conventional endpoints such as:

- `/v1/models`
- `/v1/chat/completions`
- `/v1/embeddings`

Provider-specific behavior is handled conservatively. For example, asymmetric embedding models that explicitly report that `input_type` is required are retried using `input_type="query"`. Unrelated HTTP 400 errors are not blindly retried with provider-specific parameters.

A provider may expose models in its catalog that are not callable for the current account or endpoint. Those models are classified separately from genuinely broken models.

## Model states

- `NEW` — discovered but not evaluated yet.
- `ACTIVE` — passed its supported probe and, where applicable, compatible benchmark profile.
- `UNSTABLE` — usable, but transient failures or partial benchmark failures were observed.
- `NOT_AVAILABLE` — discovered, but not callable with the current provider/account/endpoint. HTTP 404 invocation responses normally map here.
- `INCOMPATIBLE` — the attempted generic request shape does not match the model capability.
- `UNSUPPORTED` — capability is known, but this release has no safe generic probe or benchmark path for it.
- `FAILED` — a definitive non-transient failure occurred on the correct supported capability path.
- `DISABLED` — manually excluded.
- `MISSING` — previously known but no longer returned by discovery.

A later retest does not rewrite the final-status summary of an earlier run.

## Capabilities

Capabilities are stored independently of model health:

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

Detection is conservative and may use provider metadata, model-ID heuristics, probe feedback or an explicit manual source. Capability inference alone never marks a model as failed.

## Retry and classification rules

The default error policy distinguishes provider/account availability from model quality:

- `401` / `403` → authentication/provider run issue; not a model failure;
- `404` → `NOT_AVAILABLE`; no identical retry;
- `429` → rate limited; bounded retry using 1/2/5/10 seconds or `Retry-After` when supplied;
- `503` → overloaded; bounded retry using 1/2/5/10 seconds;
- `500` / `502` / `504` → transient provider error; bounded retry using 1/3 seconds;
- timeout/network failure → transient; bounded retry using 1/3 seconds;
- capability-specific `400` mismatch → `INCOMPATIBLE`;
- deterministic payload failure on the correct request shape → `FAILED`.

A model that succeeds only after retry is classified `UNSTABLE`.

## AIPerf benchmark profile

The built-in `baseline-v1` profile is used for compatible `CHAT_TEXT` models:

- input sequence length: 128 tokens;
- output sequence length: 128 tokens;
- requests: 10;
- concurrency: 1;
- streaming: enabled;
- deterministic synthetic seed: 42.

The provider API key is passed to AIPerf through the child-process environment, never as a command-line argument. The temporary AIPerf configuration file is removed after the run.

`EMBEDDING` and other specialized capabilities are not forced through the text-generation AIPerf profile. A successful supported non-text probe may therefore finish with `SKIPPED_UNSUPPORTED_PROFILE` while the model itself is `ACTIVE`.

## Progress and history

Every selected model receives a `run_model_progress` record before execution. This makes progress exact even when many discovered models never reach AIPerf.

Example CLI output:

```text
[37/82] 45.1%  provider/model-id
Capability: CHAT_TEXT
Smoke: PASS
Stability: PASS
AIPerf: RUNNING
```

Progress stages are:

- `PENDING`
- `CAPABILITY`
- `SMOKE`
- `STABILITY`
- `BENCHMARK`
- `DONE`

A run is complete when all selected progress rows reach `DONE`.

## Credentials and secret handling

Interactive API keys are never stored in SQLite.

Credential storage order:

1. operating-system keyring when a usable backend exists;
2. encrypted local credential vault when no usable keyring exists;
3. environment-variable references for automation and container/system-service deployments.

The encrypted fallback uses a local Fernet master key and vault under the application data directory. The key and vault are protected with restrictive file modes where the operating system supports them. The local OS account remains part of the trust boundary; this fallback is not hardware-backed secret storage.

For ENV-based automation:

```bash
export PROVIDER_API_KEY='...'

llmbench provider add \
  --slug example \
  --name 'Example Provider' \
  --url 'https://provider.example.com' \
  --credential-env PROVIDER_API_KEY
```

Only the environment-variable name is persisted.

Provider errors are sanitized before persistence. Active secrets, bearer tokens, UUID-like request identifiers and account-like identifiers are redacted or normalized, and messages are length-capped.

## Data location

The default data directory is selected with `platformdirs`, so it follows the operating system/user environment instead of a hard-coded home directory.

Typical locations are:

- Linux: `~/.local/share/llmbench/`
- macOS: `~/Library/Application Support/llmbench/`
- Windows: the current user's local application-data directory under `llmbench`

Override the location anywhere with:

```bash
export LLMBENCH_DATA_DIR=/path/to/llmbench-data
```

The directory contains:

```text
llmbench.db
artifacts/
credentials/     # only when encrypted-file fallback is used
```

No project code assumes a specific username, server name or installation directory.

## AIPerf executable resolution

AIPerf is a required dependency. LLM Benchmark Manager resolves the executable in this order:

1. `LLMBENCH_AIPERF` explicit override;
2. `aiperf` installed beside the Python interpreter running `llmbench` (important for `pipx` environments);
3. `aiperf` found on `PATH`.

Example override:

```bash
export LLMBENCH_AIPERF=/custom/venv/bin/aiperf
```

## REST API

Start the API locally:

```bash
llmbench serve --host 127.0.0.1 --port 8765
```

Available API resources include:

```text
GET  /api/v1/providers
POST /api/v1/providers
GET  /api/v1/providers/{provider_id}
POST /api/v1/providers/{provider_id}/discover
GET  /api/v1/providers/{provider_id}/models

POST /api/v1/runs
GET  /api/v1/runs/{run_id}
GET  /api/v1/runs/{run_id}/progress
POST /api/v1/runs/{run_id}/cancel
GET  /api/v1/runs/{run_id}/results

GET  /api/v1/models/{model_db_id}
GET  /api/v1/models/{model_db_id}/history
```

The REST server has no built-in multi-user authentication in 0.3.0. The default bind address is loopback. Do not expose it to an untrusted network without an authentication/network-control layer such as a trusted reverse proxy or private network.

## MCP server

Start the stdio MCP server:

```bash
llmbench mcp
```

The MCP surface includes:

```text
benchmark_provider_list
benchmark_provider_get
benchmark_provider_discover
benchmark_model_list
benchmark_model_get
benchmark_model_history
benchmark_run_start
benchmark_run_status
benchmark_run_progress
benchmark_run_cancel
benchmark_run_results
benchmark_retest_unstable
benchmark_test_new_models
```

There is intentionally no MCP tool that returns raw provider credentials.

This allows an external agent (for example a model-management or model-design service) to request discovery and benchmarks without receiving the underlying secrets.

## Exports

Run data can be exported as JSON or CSV:

```bash
llmbench export RUN_ID --format json --output run.json
llmbench export RUN_ID --format csv --output run.csv
```

The SQLite database remains the authoritative local history.

## Security notes

- Provider credentials are excluded from database records and normal responses.
- AIPerf receives credentials through environment inheritance, not argv.
- Persisted provider messages are sanitized.
- Interactive secret input uses hidden terminal input.
- Provider URLs may not contain embedded username/password credentials.
- The REST service should remain private unless an external authentication layer is added.
- Anyone who can read the encrypted fallback master key and vault as the same OS user can decrypt those credentials; use an OS keyring or external secret manager where a stronger boundary is required.

See [SECURITY.md](SECURITY.md) for the disclosure and deployment policy.

## Architecture

The application is deliberately split into independent layers:

```text
CLI / REST / MCP
      |
BenchmarkService
      |
+-----+------------------+
|                        |
Provider adapter       SQLite
|                        |
Discovery/probes      history/progress
|
AIPerfRunner (CHAT_TEXT baseline)
```

The benchmark manager is not a model router and does not modify a production routing system. External systems consume its evidence through CLI, REST, MCP or exported data.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for details.

## Development and verification

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest -q
python -m build
python -m pip check
```

Before publishing a release, also test installation into a clean environment and verify that `llmbench --help` and `aiperf --version` are available from that environment.

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md). Do not include real API keys, provider account identifiers, local databases or benchmark artifacts containing private data in issues or commits.

## License

MIT. See [LICENSE](LICENSE).
