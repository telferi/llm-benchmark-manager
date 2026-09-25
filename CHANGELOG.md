# Changelog

All notable user-facing changes are documented here.

## 0.3.0 - 2026-09-25

### Added

- Portable application-data directory selection through `platformdirs`.
- Reliable AIPerf executable discovery inside the same Python/pipx environment.
- NVIDIA AIPerf 0.12.0 as a required package dependency.
- Provider-agnostic bilingual release documentation (English and Hungarian).
- Public security, contributing and architecture documentation.
- Capability-aware model lifecycle and exact persisted progress from the v0.2 work.
- Asymmetric embedding retry with `input_type="query"` only when the provider explicitly requires it.

### Changed

- Package version advanced to 0.3.0 release candidate.
- Docker installation now relies on normal package dependencies instead of separately installing AIPerf.
- Direct `BenchmarkService` artifact storage now uses the same portable data-location policy as the runtime.

### Fixed

- Historical run status summaries no longer change when a model receives a different status in a later retest.
- 404 model invocation failures are represented as `NOT_AVAILABLE` rather than generic model failure.
- Alternate valid text response shapes are recognized before classifying a response as empty.

## 0.2.0 - 2026-09-24

- Added capability-aware probes, model states, retries, exact progress, REST/MCP progress surfaces and AIPerf baseline eligibility.

## 0.1.0

- Initial standalone provider discovery, SQLite history, CLI, REST, MCP and AIPerf integration.
