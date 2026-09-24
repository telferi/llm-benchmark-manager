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

## Model lifecycle

Models are retained historically rather than deleted on failure. States are:

- `NEW`
- `ACTIVE`
- `UNSTABLE`
- `FAILED`
- `UNSUPPORTED`
- `DISABLED`
- `MISSING`

Transient provider failures such as 429, 500, 502, 503, 504 and timeouts are treated as retryable/provider instability rather than proof that a model is permanently bad.

## Test pipeline

The normal full pipeline is:

1. model discovery;
2. authentication/endpoint use;
3. one-request smoke test;
4. small stability check;
5. AIPerf baseline benchmark;
6. status classification;
7. append-only persistence of run, metrics and errors.

The `baseline-v1` profile uses ISL 128, OSL 128, 10 requests and concurrency 1.

## REST API

Start the local API server:

```bash
llmbench serve --host 127.0.0.1 --port 8765
```

API prefix: `/api/v1`.

Key resources include providers, provider model discovery, benchmark runs, results and model history. A run request returns a `run_id`; long-running work is handled by the local job manager.

Bind to a non-loopback address only behind an authentication/network-control layer appropriate for your environment.

## MCP

Start an MCP stdio server:

```bash
llmbench mcp
```

The MCP surface exposes safe provider/model/run tools including discovery, run start/status/cancel/results, unstable retest and NEW-model testing. There is deliberately no raw-secret read tool.

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

The application is designed so raw credentials do not enter SQLite, normal logs, REST responses, MCP responses, benchmark JSON records, or process arguments. Interactive secrets are stored in the OS keyring when available, with an encrypted local fallback for headless systems; ENV references remain available for automation. Provider URLs are restricted to HTTP(S) and may not embed username/password credentials.

The REST API has no built-in multi-user authentication in v0.1.0. Its default CLI bind address is loopback. Use a trusted reverse proxy, network policy, or equivalent control before exposing it remotely.

## Development

```bash
pip install -e '.[dev]'
pytest -q
python -m build
```

## License

MIT
