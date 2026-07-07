# harborrag-app

Owns operator-facing API and CLI boundaries.

## Folder ownership

```text
services/base.py + services/mock.py
api/base.py + api/mock.py
cli/base.py + cli/mock.py
```

## Team deliverables

- Implement FastAPI app factory and route controllers.
- Add stable JSON error envelopes.
- Add CLI commands with JSON output and clear exit codes.
- Keep app code calling services, not raw adapters.


## Package tests

Tests for this package live in:

```text
packages/harborrag-app/tests/
```

Run from the repository root:

```bash
pytest packages/harborrag-app/tests
```

Keep new tests in this folder when adding or changing behavior owned by this package.
