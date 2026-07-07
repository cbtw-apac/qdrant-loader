# Contributing to HarborRAG

Thanks for helping build HarborRAG. This repo is intentionally structured so multiple teammates can implement connectors, parsers, model adapters, repositories, engine services, runtime services, API/CLI surfaces, and MCP tools without stepping on each other.

## Requirements

```text
Python >= 3.12
```

Install development dependencies:

```bash
python -m pip install -e packages/harborrag-core
python -m pip install -e packages/harborrag-adapters
python -m pip install -e packages/harborrag-engine
python -m pip install -e packages/harborrag-runtime
python -m pip install -e packages/harborrag-app
python -m pip install -e packages/harborrag-mcp
python -m pip install -e packages/harborrag
python -m pip install -e ".[dev]"
```

Or with uv:

```bash
uv sync --all-packages --extra dev
```

## Architecture rules

1. `harborrag-core` is provider-free.
2. Provider SDKs belong in `harborrag-adapters` only.
3. Engine code depends on core ports and domain objects, not provider classes.
4. Runtime code coordinates jobs, supervisors, schedules, and service composition.
5. App and MCP expose safe service-level operations, not raw provider access.
6. Base classes and mocks live in the same feature family they describe.
7. Use `repositories/`, not `stores/`.

## Where to add code

### Core contracts and domain

Add shared immutable contracts, domain objects, and protocol ports here:

```text
packages/harborrag-core/src/harborrag_core/
```

Only add code here when more than one package needs the concept.

### Adapters

Add real providers here:

```text
packages/harborrag-adapters/src/harborrag_adapters/
  connectors/
  parsers/
  models/
  repositories/
```

Each provider should include tests using fake clients or deterministic mocks. Do not require live credentials in the default test suite.

### Engine

Add orchestration logic here:

```text
packages/harborrag-engine/src/harborrag_engine/
  ingestion/
  retrieval/
  indexing/
  graph/
```

Engine code should call interfaces from `harborrag-core`, not concrete providers.

### Runtime

Add job state, scheduling, supervision, and future durable workflow code here:

```text
packages/harborrag-runtime/src/harborrag_runtime/
```

### App

Add HTTP/API and CLI-facing code here:

```text
packages/harborrag-app/src/harborrag_app/
```

### MCP

Add agent tool facades here:

```text
packages/harborrag-mcp/src/harborrag_mcp/
```

MCP tools should enforce budgets, validate inputs, and return audited service-level outputs.

## Test policy

Every package owns a local test folder:

```text
packages/<package-name>/tests/
```

Add tests next to the package you modify. Root tests remain for cross-package architecture checks.

Run all tests:

```bash
make test
```

Run package tests:

```bash
make test-package PACKAGE=harborrag-core
```

Coverage:

```bash
make coverage
```

Coverage must stay at or above:

```text
95%
```

## PR checklist

Before opening a pull request:

```bash
make lint
make typecheck
make test
make coverage
make compile
make deps-check
```

A PR should include:

- package-local tests for the code changed;
- updated README or package README when behavior changes;
- mock/fake-client tests for provider adapters;
- no live credential requirement in default tests;
- no provider SDK imports in `harborrag-core`;
- no new `stores/` folders.

## TODO comment policy

TODO comments should explain exactly how the next teammate should continue the implementation.

Good:

```python
# TODO(connectors/jira): Add incremental sync using the updated timestamp cursor.
# TODO(parsers/pdf): Convert detected tables into DocumentTable objects with page numbers.
# TODO(repositories/vector): Add provider capability tests for dense, sparse, and hybrid search.
```

Avoid:

```python
# TODO(later): finish this later
# TODO(next): clean up
# TODO: improve
```

## Commit style

Prefer small, focused commits:

```text
core: add document permission contract
adapters: add qdrant vector repository mock tests
engine: add section-aware chunker base class
runtime: add in-memory job state transitions
app: add doctor command JSON contract
mcp: add retrieval tool budget validation
```

## Integration tests

Tests requiring Docker, cloud credentials, provider accounts, model APIs, or live services must be opt-in and marked:

```python
@pytest.mark.integration
```

Default CI should not require external services.
