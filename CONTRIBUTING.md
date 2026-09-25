# Contributing

Thank you for contributing to LLM Benchmark Manager.

## Development setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest -q
```

## Change rules

- Keep the benchmark core independent from any particular agent or router.
- Never hard-code local usernames, host names, home directories or deployment paths.
- Provider-specific behavior must be narrowly detected; do not apply a provider workaround to unrelated errors.
- Preserve historical run data. A later retest must not rewrite old run outcomes.
- Never expose raw credentials through CLI output, REST, MCP, logs, reports or process arguments.
- Add or update tests for behavior changes and run the full test suite before submitting a change.
- Keep public documentation in English and Hungarian when a user-facing workflow changes.

## Before submitting

```bash
pytest -q
python -m compileall -q src
python -m build
python -m pip check
```

Also scan the change for credentials, local paths, databases and generated artifacts.

## Generated/local files

Do not commit `.venv`, `dist`, `build`, `*.egg-info`, `.pytest_cache`, local databases, `.env` files, credentials or benchmark artifacts.
