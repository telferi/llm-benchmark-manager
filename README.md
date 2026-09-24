# LLM Benchmark Manager

A standalone, provider-agnostic tool for discovering LLM models, screening them for basic reliability, benchmarking healthy models with NVIDIA AIPerf, and preserving historical results in SQLite.

The same core is exposed through:

- an interactive and automation-friendly CLI;
- a REST API;
- an MCP server for AI/agent clients such as Hermes or ChatGPT.

It is intentionally independent of any one agent or routing system.

## Requirements

- Python 3.11+
- AIPerf for performance benchmark runs (discovery and inventory functions work without it)

The project is tested with AIPerf 0.12.0. Set `LLMBENCH_AIPERF` if the executable is not on `PATH`.

## Install

Primary installation:

```bash
pipx install llm-benchmark-manager
```

Install AIPerf separately if performance benchmarks are needed:

```bash
pipx install aiperf==0.12.0
```

For a local source checkout:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

## Credentials

Interactive onboarding is intentionally simple: the user enters only the provider endpoint URL and the API key. The provider name/slug is derived automatically from the endpoint hostname. If the same endpoint already exists (for example from an earlier ENV-based setup), the existing provider is reused and its credential binding is upgraded instead of creating a duplicate.

```text
New provider
Endpoint URL: https://integrate.api.nvidia.com
API key: ***************
```

The raw API key is never written to SQLite. LLM Benchmark Manager first tries the operating system keyring (macOS Keychain, Windows Credential Manager, or an available Linux Secret Service backend). On headless systems where no secure OS keyring backend is available, it falls back to an encrypted local vault protected by mode-0600 files inside the application data directory.

The encrypted-file fallback keeps a local master key under the same OS user account, so operating-system account isolation remains part of the trust boundary. It is intended to prevent plaintext secrets from appearing in the database, reports, logs, artifacts, or ordinary configuration files.

Environment-variable credentials remain supported for automation, containers, systemd and existing Hermes-style deployments:

```bash
export NVIDIA_API_KEY='...'

llmbench provider add \
  --slug nvidia \
  --name 'NVIDIA NIM' \
  --url 'https://integrate.api.nvidia.com' \
  --credential-env NVIDIA_API_KEY
```

In ENV mode the manager stores only the variable name. In all modes, AIPerf receives the provider key through its child environment, never as a command-line argument.

## Interactive use

Run with no arguments:

```bash
llmbench
```

The main menu offers new-provider setup, selection of an existing provider, all-provider retesting, previous results, and settings/help. New-provider setup asks only for endpoint URL and a hidden API key; provider identity is derived automatically.

For an existing provider the interactive workflow supports full retest, ACTIVE-only retest, UNSTABLE/FAILED retest, refresh + NEW-only test, single-model test, and model listing.

## Automation CLI

```bash
llmbench provider list
llmbench provider discover nvidia
llmbench run nvidia --mode full
llmbench run nvidia --mode new
llmbench run nvidia --mode active
llmbench run nvidia --mode unstable_failed
llmbench run --all --mode full
llmbench model test nvidia nvidia/nemotron-3-super-120b-a12b
llmbench results RUN_ID
llmbench history nvidia MODEL_ID
llmbench export RUN_ID --format json --output run.json
llmbench export RUN_ID --format csv --output run.csv
```

## Model lifecycle and capabilities

Models are retained historically rather than deleted when a run cannot use them. v0.2 distinguishes model health from provider/account availability and from request-shape compatibility.

States are:

- `NEW` — discovered but not yet evaluated;
- `ACTIVE` — passed the appropriate supported probe and, where a matching profile exists, benchmark;
- `UNSTABLE` — usable, but transient failures or partial benchmark errors were observed;
- `NOT_AVAILABLE` — present in discovery but not callable with the current provider/account/endpoint. Invocation HTTP 404 belongs here and is not treated as proof that the model itself is broken;
- `INCOMPATIBLE` — the attempted generic request shape does not match the model capability, for example text input sent to a non-text model;
- `UNSUPPORTED` — capability is known but this release has no safe generic probe/benchmark path for it;
- `FAILED` — a definitive non-transient failure occurred on the correct supported capability path;
- `DISABLED` — manually excluded;
- `MISSING` — previously known but no longer returned by discovery.

Capabilities are persisted separately from status: `CHAT_TEXT`, `EMBEDDING`, `VISION`, `MULTIMODAL`, `PARSER`, `TRANSLATION`, `SAFETY`, `RERANK`, `SPECIAL`, and `UNKNOWN`. Detection prefers provider metadata, then conservative model-name hints, then probe feedback. Capability inference never by itself marks a model failed.

Transient 429/503 errors use bounded 1/2/5/10 second retries. 500/502/504 and timeout/network errors use bounded 1/3 second retries. Deterministic 4xx capability/auth/availability errors are not retried with the same request. A model that succeeds only after retry is `UNSTABLE`.

## Test pipeline

A v0.2 full run is capability-aware:

1. model discovery;
2. capability detection and persistence;
3. capability-specific smoke probe;
4. bounded stability checks;
5. capability/profile eligibility decision;
6. AIPerf only when a compatible profile exists;
7. final status plus append-only metrics/errors/history.

`CHAT_TEXT` is eligible for the existing AIPerf `baseline-v1` profile (ISL 128, OSL 128, 10 requests, concurrency 1). `EMBEDDING` uses `/v1/embeddings` for probe validation and is not sent through the text-generation AIPerf baseline. Other specialized capabilities are retained as `UNSUPPORTED` unless an explicit safe adapter/profile exists.

Valid OpenAI-compatible text responses may be read from ordinary `message.content`, structured text content, reasoning-content variants, `choices[].text`, or supported output-text variants. Usage-only/empty responses are not counted as success.

## Live progress

Every selected model gets a persisted `run_model_progress` row before execution. The progress denominator is therefore the number of models selected for the run; `processed` means rows that reached `DONE`, not the number of models with AIPerf result rows.

Interactive CLI runs print stage transitions such as:

```text
[37/82] 45.1%  nvidia/model-id
Capability: CHAT_TEXT
Smoke: RUNNING
```

The final CLI summary reports `ACTIVE`, `UNSTABLE`, `NOT_AVAILABLE`, `INCOMPATIBLE`, `UNSUPPORTED`, `FAILED`, and the exact total processed.

## REST API

Start the local API server:

```bash
llmbench serve --host 127.0.0.1 --port 8765
```

API prefix: `/api/v1`.

Key resources include providers, provider model discovery, benchmark runs, results, model history, and persisted live progress. A run request returns a `run_id`; long-running work is handled by the local job manager. Read exact progress with `GET /api/v1/runs/{run_id}/progress`.

Bind to a non-loopback address only behind an authentication/network-control layer appropriate for your environment.

## MCP

Start an MCP stdio server:

```bash
llmbench mcp
```

The MCP surface exposes safe provider/model/run tools including discovery, run start/status/progress/cancel/results, unstable retest and NEW-model testing. `benchmark_run_progress` returns the same persisted progress summary as REST. There is deliberately no raw-secret read tool.

Hermes and other agents should call this MCP/API surface instead of gaining direct access to provider credentials.

## Data location

Default data directory:

```text
~/.local/share/llmbench/
```

Override it with:

```bash
export LLMBENCH_DATA_DIR=/srv/llmbench
```

Contents include the SQLite database, AIPerf artifact directories, and (when OS keyring is unavailable) the encrypted credential vault. Benchmark history is append-only across reruns.

## Docker

Build:

```bash
docker build -t llm-benchmark-manager .
```

Example API mode:

```bash
docker run --rm \
  --env-file providers.env \
  -p 8765:8765 \
  -v llmbench-data:/data \
  llm-benchmark-manager serve --host 0.0.0.0 --port 8765
```

The Docker image installs AIPerf 0.12.0 and stores application data under `/data`.

## Security model

The application is designed so raw credentials do not enter SQLite, normal logs, REST responses, MCP responses, benchmark JSON records, or process arguments. Provider error text is sanitized before persistence: active credentials and bearer tokens are redacted, UUID-like request/function identifiers and account-like identifiers are replaced with placeholders, and stored messages are length-capped while preserving the semantic error class. Interactive secrets are stored in the OS keyring when available, with an encrypted local fallback for headless systems; ENV references remain available for automation. Provider URLs are restricted to HTTP(S) and may not embed username/password credentials.

The REST API has no built-in multi-user authentication in v0.2.0. Its default CLI bind address is loopback. Use a trusted reverse proxy, network policy, or equivalent control before exposing it remotely.

## Development

```bash
pip install -e '.[dev]'
pytest -q
python -m build
```

## License

MIT
