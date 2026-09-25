# Security Policy

## Supported release

The current development release is 0.3.x.

## Reporting a vulnerability

Until a public repository and dedicated security contact are published, do not post credentials, exploit details, private provider responses, local databases, or benchmark artifacts in public channels. When the project is published, the repository should enable private vulnerability reporting or document a private security contact before accepting public security reports.

## Credential model

LLM Benchmark Manager is designed to keep raw provider keys out of SQLite, normal logs, REST responses, MCP responses, benchmark result records, and process arguments.

Interactive credentials are stored in the OS keyring when possible. If no usable keyring backend exists, an encrypted local Fernet vault is used. Its master key is stored under the same OS user account, so local account isolation is part of the trust boundary. Use an external secret manager or OS keyring when a stronger boundary is required.

Environment-variable references are supported for automation. Only the variable name is persisted.

## Network model

The REST API does not implement multi-user authentication in 0.3.0. Keep it bound to loopback or protect it with a trusted reverse proxy, private network, firewall and authentication layer.

The MCP stdio server is intended to be launched by a trusted local client. It exposes no raw-secret read tool.

## Data and logs

Provider error messages are sanitized before persistence. Nevertheless, operators should treat the application data directory and exported benchmark results as operational data and protect them according to their environment.

Never commit:

- `.env` files;
- local SQLite databases;
- encrypted credential vaults or master keys;
- provider API keys or bearer tokens;
- raw private provider traces;
- benchmark artifacts containing sensitive prompts or data.
