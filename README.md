# HarborRAG

HarborRAG is a modular, provider-agnostic Retrieval-Augmented Generation framework for engineering knowledge. It is designed around clear package boundaries: **core** defines stable contracts, **adapters** implement providers, **engine** orchestrates ingestion/retrieval, **runtime** owns jobs and scheduling, **app** exposes CLI/API surfaces, and **MCP** exposes audited agent tools.

> Status: framework foundation. This repository currently provides abstract base classes, protocol contracts, package-local mock implementations, tests, and scripts so teammates can implement real providers without breaking architecture boundaries.

## Why HarborRAG?

Engineering RAG is not only “put files into a vector database.” A production system needs:

- connectors for sources such as GitHub, Jira, Confluence, local files, and web content;
- parsers for text, Office documents, PDFs, OCR-heavy files, and structured layouts;
- model adapters for chat, embedding, and reranking providers;
- repositories for vector, graph, cache, object, database, and state storage;
- ingestion and retrieval pipelines that remain independent from provider SDKs;
- runtime services for jobs, supervisors, schedules, and future durable workflows;
- API/CLI/MCP surfaces that expose safe operations instead of raw provider access.

HarborRAG uses a ports-and-adapters layout so each of these responsibilities can evolve independently.

## Requirements

```text
Python >= 3.12
```

The workspace is configured with `pyproject.toml`, package-local `src/` layouts, and `uv` workspace members.

## Package map

```text
packages/
  harborrag-core/      contracts, domain models, ports, execution, security
  harborrag-adapters/  connectors, parsers, models, repositories, mocks
  harborrag-engine/    ingestion, retrieval, indexing, graph orchestration
  harborrag-runtime/   jobs, supervision, scheduling, runtime services
  harborrag-app/       application service, API controller, CLI command boundary
  harborrag-mcp/       MCP tools/server facade with policy and audit boundaries
  harborrag/           future public facade / meta-package
```

## Structure rules

1. Base classes and mocks live inside the matching feature folder.
2. Storage implementations are called `repositories`, not `stores`.
3. `harborrag-core` must not import adapters, engine, runtime, app, MCP, or the meta-package.
4. Engine code depends on core ports/contracts, not provider SDKs.
5. Runtime coordinates jobs and services; it does not contain ingestion/retrieval business logic.
6. App and MCP call service-level facades; they do not call raw provider clients directly.
7. TODO comments must tell the next implementer exactly what to build next.

## Current skeleton examples

```text
harborrag_adapters/
  connectors/base.py
  connectors/mock.py
  parsers/base.py
  parsers/mock.py
  models/chat/base.py
  models/chat/mock.py
  models/embedding/base.py
  models/embedding/mock.py
  models/reranker/base.py
  models/reranker/mock.py
  repositories/vector/base.py
  repositories/vector/mock.py
  repositories/graph/base.py
  repositories/graph/mock.py
  repositories/cache/base.py
  repositories/cache/mock.py
  repositories/object_store/base.py
  repositories/object_store/mock.py
  repositories/database/base.py
  repositories/database/mock.py
```

Engine, runtime, app, and MCP follow the same rule:

```text
harborrag_engine/ingestion/base.py     harborrag_engine/ingestion/mock.py
harborrag_runtime/jobs/base.py         harborrag_runtime/jobs/mock.py
harborrag_app/services/base.py         harborrag_app/services/mock.py
harborrag_mcp/tools/base.py            harborrag_mcp/tools/mock.py
```

## Quick start

### Option A — pip editable install

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

### Option B — uv workspace

```bash
uv sync --all-packages --extra dev
uv run pytest
```

## Run the mock pipeline

```bash
python scripts/run_mock_pipeline.py --json
```

Expected shape:

```json
{
  "documents": [...],
  "chunks": [...],
  "retrieval": [...]
}
```

## CLI

```bash
python -m harborrag_app.cli.main doctor --json
python -m harborrag_app.cli.main sample-ingest --json
```

## MCP mock tools

```python
from harborrag_mcp.server import call_tool

print(call_tool("harbor_health_check"))
print(call_tool("harbor_sample_retrieve", {"query": "HarborRAG"}))
```

## Tests

Every package owns its own `tests/` folder:

```text
packages/harborrag-core/tests/
packages/harborrag-adapters/tests/
packages/harborrag-engine/tests/
packages/harborrag-runtime/tests/
packages/harborrag-app/tests/
packages/harborrag-mcp/tests/
packages/harborrag/tests/
```

Run all tests:

```bash
pytest
pytest --cov --cov-report=term-missing
```

Run one package:

```bash
make test-package PACKAGE=harborrag-core
make test-package PACKAGE=harborrag-adapters
make test-package PACKAGE=harborrag-engine
```

Coverage gate:

```text
95% minimum
```

## Makefile commands

```bash
make help
make bootstrap
make test
make coverage
make lint
make format
make typecheck
make compile
make doctor
make mock-pipeline
make deps-check
make provider-matrix
make clean
```

## How to implement real providers

### Connector

Create a provider folder under `harborrag_adapters/connectors/`:

```text
connectors/github/
  __init__.py
  client.py
  connector.py
  schemas.py
  mock.py
```

Implementation requirements:

- subclass `harborrag_adapters.connectors.base.BaseConnector`;
- return core `SourceRecord` objects from `discover()`;
- return core `RawDocument` objects from `load()`;
- keep provider SDK imports out of `harborrag-core`;
- add provider-local tests under `packages/harborrag-adapters/tests/`.

### Parser

Create a provider folder under `harborrag_adapters/parsers/`:

```text
parsers/pdf/docling_engine.py
parsers/pdf/pypdf_engine.py
parsers/office/docx_engine.py
```

Implementation requirements:

- subclass `harborrag_adapters.parsers.base.BaseParser`;
- return core `ParsedDocument` objects;
- preserve layout/tables/page metadata when available;
- return warnings instead of silently dropping partial parsing issues;
- include a deterministic mock or fake-engine path for tests.

### Repository

Use `repositories/`, not `stores/`:

```text
repositories/vector/qdrant.py
repositories/graph/neo4j.py
repositories/cache/redis.py
repositories/object_store/s3.py
repositories/database/postgresql.py
```

Implementation requirements:

- subclass the matching base class in the repository family;
- keep raw provider responses out of public results by default;
- expose capability metadata in the provider module;
- add mock/fake-client tests for request/response normalization.

## TODO comment style

Use TODO comments as direct implementation instructions:

```python
# TODO(connectors/github): Implement pagination and rate-limit handling for GitHub REST responses.
# TODO(parsers/pdf): Preserve table bounding boxes when the selected engine exposes layout coordinates.
# TODO(repositories/vector): Normalize provider-specific scores into HarborRAG retrieval scores.
```

Avoid vague placeholders such as `TODO(later)` or `TODO(next)` because they do not tell the next implementer what to do.

## Repository quality checks

```bash
make deps-check
make compile
make test
make coverage
```

## Documentation files

```text
README.md              project overview and quickstart
CONTRIBUTING.md        development workflow and PR rules
SECURITY.md            vulnerability reporting and security expectations
CODE_OF_CONDUCT.md     community behavior expectations
CHANGELOG.md           release notes
TEST_TUTORIAL.md       test and coverage guide
```

## License

See [LICENSE](LICENSE).
