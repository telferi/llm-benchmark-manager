# Architecture

## Design goal

LLM Benchmark Manager is an evidence-producing service. It discovers and tests models, records what happened, and exposes the evidence. It deliberately does **not** decide production routing and does not require any particular agent framework or routing platform.

## Main components

### Surfaces

- **CLI** — interactive use and shell automation.
- **REST API** — local/controlled network automation.
- **MCP server** — agent/tool integration without credential disclosure.

All surfaces call the same `BenchmarkService` core.

### BenchmarkService

Coordinates provider discovery, model selection, capability detection, smoke/stability probes, retry policy, AIPerf eligibility, final classification and persistence.

### Provider adapter

The default adapter implements an OpenAI-compatible interface for model listing, chat probes and embedding probes. Provider-specific behavior must be triggered by explicit response evidence rather than provider-name assumptions where possible.

### Capability layer

Capability is stored independently from health. Detection may use metadata, conservative model-ID heuristics and probe evidence. Unknown/specialized models are retained rather than forced through the wrong request shape.

### AIPerf adapter

AIPerf 0.12.0 is a required Python dependency. The current `baseline-v1` profile is available to compatible `CHAT_TEXT` models. Credentials are injected into the child environment and temporary config files are removed after execution.

### SQLite

SQLite stores:

- providers;
- discovered models;
- capability metadata;
- benchmark runs;
- per-model progress;
- benchmark metrics;
- normalized errors;
- status history.

Historical runs are immutable evidence: later model-state changes do not rewrite earlier run summaries.

### Credential manager

Credential values are resolved only when a provider call needs them. Storage may use the OS keyring, encrypted-file fallback or ENV references. Database rows contain references/source metadata, not raw API keys.

## Data flow

```text
provider discovery
      |
selected run models
      |
capability detection
      |
capability-aware smoke
      |
stability / bounded retry
      |
profile eligibility
      +---- no compatible profile ---> final classification
      |
AIPerf baseline
      |
final classification
      |
SQLite history + progress + metrics/errors
```

## Integration boundary

An external model-management system can treat the benchmark manager as a source of evidence:

```text
Model Designer / automation
          |
       MCP/REST
          |
LLM Benchmark Manager
          |
 evidence/history
```

The external system may decide how to promote or schedule models, but that policy is intentionally outside this repository.
