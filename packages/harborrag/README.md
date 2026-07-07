# harborrag

Meta-package for future public facade re-exports.

## Team deliverables

- Re-export stable public APIs only after they are implemented and documented.
- Do not hide package boundaries by adding heavy logic here.


## Package tests

Tests for this package live in:

```text
packages/harborrag/tests/
```

Run from the repository root:

```bash
pytest packages/harborrag/tests
```

Keep new tests in this folder when adding or changing behavior owned by this package.
