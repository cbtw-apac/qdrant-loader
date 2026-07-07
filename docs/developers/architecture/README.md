# Architecture Overview

HarborRAG uses a ports-and-adapters (hexagonal) layout: each responsibility — contracts, providers, orchestration, runtime, API/CLI, agent tools — lives in its own package, and packages may only depend downward in a fixed direction.

## Package map

```text
packages/
  harborrag-core/      contracts, domain models, ports, execution, observability, security
  harborrag-adapters/  connectors, parsers, models, repositories, mocks
  harborrag-engine/    ingestion, retrieval, indexing, graph orchestration
  harborrag-runtime/   jobs, supervision, scheduling, runtime services
  harborrag-app/       application service, API controller, CLI command boundary
  harborrag-mcp/       MCP tools/server facade with policy and audit boundaries
  harborrag/           public facade / meta-package
```

## Dependency direction

```text
harborrag_core      -> (no HarborRAG dependencies)
harborrag_adapters  -> core
harborrag_engine    -> core, adapters
harborrag_runtime   -> core, adapters, engine
harborrag_app       -> core, engine, runtime
harborrag_mcp       -> core, engine, runtime
harborrag           -> any package (public facade)
```

This is enforced mechanically, not just by convention:

```bash
python scripts/check_dependency_direction.py
make deps-check
```

Any import that violates the table above fails CI (`.github/workflows/quality-gates.yml`).

## The base + mock pattern

Every provider family — connector, parser, chat/embedding/reranker model, vector/graph/cache/object-store/database repository, ingestion/retrieval stage, job store, scheduler, supervisor, runtime service, app service, MCP tool — follows the same shape:

```text
<family>/
  base.py    abstract class or Protocol defining the contract
  mock.py    deterministic, dependency-free implementation used by tests and the mock pipeline
```

Tests exercise `base.py` through `mock.py` so the framework's plumbing is verified before any real provider exists. When a teammate implements a real provider, it becomes a sibling module next to `mock.py` (see [Extending HarborRAG](../extending/README.md)) — the base contract does not change.

## `harborrag-core`: contracts, domain, ports

Core has zero dependencies on other HarborRAG packages and no provider SDK imports. It is organized into five areas:

### `contracts/` — small, stable, provider-agnostic types

- `result.py` — `Result[T]`, a success/failure wrapper (`Result.success(value)` / `Result.failure(error)` / `.unwrap()`).
- `ids.py` — `HarborId` (a validated `harbor://` URI) and `stable_hash_id(namespace, *parts)` for deterministic IDs.
- `capabilities.py` — `CapabilityProfile`, a declarative flag set (`sync`, `async_`, `streaming`, `batch`, `permissions`, `metadata`) a provider can assert and callers can `.require(...)`.
- `events.py` — `HarborEvent`, a trace-correlated event envelope.
- `errors.py` — the error hierarchy: `HarborError`, `HarborConfigurationError`, `HarborCapabilityError`, `HarborSecurityError`, `HarborDeadlineExceeded`.

### `domain/` — the shapes that flow through ingestion and retrieval

`SourceRecord` → `RawDocument` → `ParsedDocument` → `HarborDocument` is the ingestion pipeline's document lifecycle:

- `source.py` (`SourceRecord`) — what a connector discovers before loading.
- `raw_document.py` (`RawDocument`) — the connector's loaded output.
- `parsed_document.py` (`ParsedDocument`) — the parser's structured output.
- `element.py` (`DocumentElement`) — a heading/paragraph/table/image/code/metadata element within a document.
- `document.py` (`HarborDocument`) — the normalized document the engine embeds and indexes.
- `metadata.py` (`DocumentMetadata`), `provenance.py` (`DocumentProvenance`) — metadata and connector/parser provenance attached to a document.
- `graph.py` (`GraphHint`) — a subject/predicate/object hint for graph repositories.
- `chunk.py` — chunk-level shapes produced during ingestion.
- `retrieval.py` (`RetrievalQuery`, `RetrievalResult`) — the retrieval-side query/result pair.
- `tenant.py` (`Tenant`) — a validated tenant identifier (non-empty, no whitespace).

### `ports/` — `Protocol` contracts adapters must satisfy

- `connector.py` — `ConnectorPort` (`discover()` / `load()`).
- `parser.py` — `ParserPort` (`parse()`).
- `models.py` — `ChatModelPort`, `EmbeddingModelPort`, `RerankerPort`.
- `repositories.py` — `VectorRepositoryPort`, `GraphRepositoryPort`, `CacheRepositoryPort`, `ObjectRepositoryPort`, `DatabaseRepositoryPort`.

These are `typing.Protocol` definitions, not base classes — `harborrag-adapters`' `base.py` files provide the abstract-class version of the same contracts that adapters actually subclass.

### `execution/` — request-scoped budgets and deadlines

- `context.py` (`RequestContext`) — carries `trace_id`, `tenant`, and an optional `deadline_seconds` through a call chain; `.child()` derives a scoped copy.
- `deadlines.py` (`Deadline`) — wall-clock deadline tracking; `.check()` raises `HarborDeadlineExceeded` once expired.
- `budgets.py` (`CapabilityBudget`) — caps like `max_documents`, `max_bytes`, `max_tool_calls`.

### `security/` and `observability/`

- `security/redaction.py` — `redact_secrets(text)` masks API keys, tokens, secrets, passwords, and bearer tokens in log/error text.
- `security/url_policy.py` — `UrlPolicy` validates a URL's scheme against an allow-list and its host against a deny-list before a connector fetches it.
- `observability/events.py` — `InMemoryEventBus` (publish/collect `HarborEvent`s).
- `observability/metrics.py` — `InMemoryMetrics` (counters and observations, both label-aware).

### `testing/fakes.py`

`FakeConnector` and `FakeParser` — deterministic fakes for tests that need connector/parser behavior without depending on `harborrag-adapters`.

## `harborrag-engine`: orchestration

- `builder.py` (`EngineBuilder`) + `config.py` (`EngineConfig`: `tenant`, `environment`) + `policy.py` (`EnginePolicy`: `max_concurrency`, `retrieval_top_k`) — engine-level configuration and diagnostics.
- `ingestion/` — `BaseDocumentNormalizer`, `BaseChunker`, `BaseIngestionPipeline` (contracts) and `MockDocumentNormalizer`, `MockChunker`, `MockIngestionPipeline` (mocks). `IngestionRunSummary` reports `discovered`/`loaded`/`parsed`/`indexed` counts.
- `retrieval/` — `BaseRetrievalPipeline`, `BaseEvidenceBuilder` (contracts) and `MockRetrievalPipeline`, `MockEvidenceBuilder` (mocks), plus `fusion.py` (`reciprocal_rank_fusion`), `reranking.py`, and `rewriting.py` for later hybrid-retrieval stages.
- `indexing/` and `graph/` — `BaseIndexer`/`MockIndexer` and `BaseGraphMapper`/`MockGraphMapper` for future indexing and graph-hint mapping stages.

Engine code depends only on `harborrag-core` ports/domain and `harborrag-adapters` base classes — never on a concrete provider.

## `harborrag-runtime`: composition, jobs, scheduling

- `composition.py` (`CompositionRoot`) — the single place that wires connector + parser + embedder + vector repository into a pipeline today (`mock_pipeline()`); this hard-coded assembly is meant to become configuration-driven.
- `job_state.py` (`JobState`, `InMemoryJobStore`) and `jobs/` (`BaseJobStore`/`MockJobStore`) — job persistence contracts.
- `scheduling/` (`BaseScheduler`/`MockScheduler`) and `schedules.py` (`ScheduleSpec`) — scheduled-job contracts.
- `supervision/` (`BaseSupervisor`/`MockSupervisor`) and `supervisor.py` (`LocalSupervisor`) — bounded local worker execution.
- `services/` (`BaseRuntimeService`/`MockRuntimeService`) — the facade `harborrag-app` and `harborrag-mcp` call instead of touching adapters directly.
- `temporal/` — optional durable-workflow integration; every file is currently a TODO placeholder kept behind this package so Temporal never becomes a hard dependency of core/adapters/engine.

## `harborrag-app`: CLI and API boundary

- `services/` (`BaseAppService`/`MockAppService`) — the only thing the CLI and HTTP layers call.
- `cli/main.py` — the real `harbor` entry point today (`doctor`, `sample-ingest`); `cli/commands/*.py` are TODO stubs for a future `doctor`/`ingest`/`retrieve`/`status` subcommand split.
- `api/` — `dependencies.py` (`get_app_service()`), `app.py` (`create_app_state()` placeholder for a future FastAPI app), and `routes/*.py` TODO stubs for HTTP route handlers that will call the service layer, not adapters.

See [CLI Reference](../../users/cli-reference/README.md) for what's runnable today.

## `harborrag-mcp`: audited agent tools

- `tools/` (`BaseMcpTool`/`MockHealthTool`, `MockRetrieveTool`) — each tool declares an `McpToolSpec` (name, description, JSON input schema) and implements `call()`.
- `server/` (`BaseMcpServer`/`MockMcpServer`) — dispatches `call_tool(name, arguments)` to the matching tool.
- `policy.py` (`McpToolPolicy`) — result-count budgets (`max_results`) and ingestion allow/deny.
- `audit.py` (`McpAuditLog`) — records which tools were called.
- `schemas.py` (`tool_schema`) — the MCP tool-schema envelope shape.

See [MCP Mock Tools](../../users/detailed-guides/mcp-server/README.md) for the tool list.

## `harborrag`: public facade

A thin meta-package that re-exports the stable public surface — currently `CompositionRoot`, `HarborDocument`, `HarborId`, and `stable_hash_id` — so downstream code can `import harborrag` instead of reaching into individual packages. New re-exports should only be added once an API is implemented and documented, per the package's own README.

## Related

- [Extending HarborRAG](../extending/README.md) — how to add a real provider without breaking these rules.
- [Testing](../testing/README.md) — how the base + mock pattern is verified.
- [Deployment](../deployment/README.md) — the `deploy/` stack this architecture is designed to run against.
