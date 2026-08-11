# Contributing

## Setup

```bash
make install
cp .env.example .env
make test
```

Use focused changes, include tests for behavioral changes, and do not commit API Keys, SQLite workspaces, uploaded data, or generated build output.

## Pull Requests

1. Explain the user-visible behavior and the Rule lifecycle affected by the change.
2. Add or update tests in proportion to the change.
3. Run `make test`.
4. Keep provider-specific code behind the provider boundary.

## Product Constraints

- v0.1 is single-label text classification only.
- Embeddings may retrieve cases and cluster failures, but cannot define business truth.
- Rule changes require human confirmation and a new Standard version.
- `AUTO_ACCEPT` requires complete Rule checks and an independent Verifier pass.

