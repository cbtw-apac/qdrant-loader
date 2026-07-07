# harborrag-adapters

Owns provider implementation base classes and mocks for connectors, parsers, models, and repositories.

## Folder ownership

```text
connectors/base.py + connectors/mock.py
parsers/base.py + parsers/mock.py
models/chat/base.py + models/chat/mock.py
models/embedding/base.py + models/embedding/mock.py
models/reranker/base.py + models/reranker/mock.py
repositories/vector/base.py + repositories/vector/mock.py
repositories/graph/base.py + repositories/graph/mock.py
repositories/cache/base.py + repositories/cache/mock.py
repositories/object_store/base.py + repositories/object_store/mock.py
repositories/database/base.py + repositories/database/mock.py
```

## Team deliverables

- Implement real providers next to the matching base/mock files.
- Keep provider SDK imports inside provider modules.
- Add clear errors for missing optional dependencies.
- Add capability profiles beside concrete providers.
- Use `repositories/`, not `stores/`.


## Package tests

Tests for this package live in:

```text
packages/harborrag-adapters/tests/
```

Run from the repository root:

```bash
pytest packages/harborrag-adapters/tests
```

Keep new tests in this folder when adding or changing behavior owned by this package.
