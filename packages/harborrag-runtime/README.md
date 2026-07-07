# harborrag-runtime

Owns local jobs, worker supervision, scheduling, runtime services, and future durable workflow integration.

## Folder ownership

```text
jobs/base.py + jobs/mock.py
supervision/base.py + supervision/mock.py
scheduling/base.py + scheduling/mock.py
services/base.py + services/mock.py
```

## Team deliverables

- Implement durable job store.
- Implement bounded worker supervisor.
- Implement store-backed schedules.
- Add optional Temporal workflows without making Temporal a core dependency.


## Package tests

Tests for this package live in:

```text
packages/harborrag-runtime/tests/
```

Run from the repository root:

```bash
pytest packages/harborrag-runtime/tests
```

Keep new tests in this folder when adding or changing behavior owned by this package.
