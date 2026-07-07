# Extending HarborRAG

HarborRAG extends through real implementations of the base classes already defined in `harborrag-adapters`, `harborrag-engine`, and `harborrag-runtime`. Every family below follows the same shape: subclass `base.py`, keep provider SDK imports out of `harborrag-core`, and add a package-local test using a fake client or the deterministic mock — never live credentials in the default test suite. See [Architecture Overview](../architecture/README.md#the-base-mock-pattern) for why this pattern exists.

## Connectors

Location: `packages/harborrag-adapters/src/harborrag_adapters/connectors/`

Contract (`connectors/base.py`, `BaseConnector`):

```python
def discover(self) -> Iterable[SourceRecord]: ...
def load(self, record: SourceRecord) -> RawDocument: ...
```

`MockConnector` and `MockLocalTextFileConnector` in `connectors/mock.py` show the pattern: `discover()` yields lightweight `SourceRecord`s, `load()` returns the full `RawDocument`.

To add a real connector (e.g. GitHub, Confluence, Jira, a local filesystem walker):

```text
connectors/github/
  __init__.py
  client.py       # thin provider SDK/HTTP client wrapper
  connector.py    # subclasses BaseConnector, returns SourceRecord/RawDocument
  schemas.py      # provider-specific request/response shapes
  mock.py         # or reuse connectors/mock.py's pattern for this provider
```

Requirements: support include/exclude filtering, checksums for change detection, a binary-file policy, a symlink policy, and file-size limits; keep the provider SDK import inside this folder, never in `harborrag-core` or `harborrag-engine`.

## Parsers

Location: `packages/harborrag-adapters/src/harborrag_adapters/parsers/`

Contract (`parsers/base.py`, `BaseParser`):

```python
def parse(self, raw: RawDocument) -> ParsedDocument: ...
```

`MockMarkdownParser` splits on blank lines and classifies each block as a `heading` or `paragraph` `DocumentElement` — enough to exercise the ingestion pipeline without a real parsing library.

To add a real parser (PDF, Office documents, HTML):

```text
parsers/pdf/docling_engine.py
parsers/pdf/pypdf_engine.py
parsers/office/docx_engine.py
```

Requirements: return `ParsedDocument` with `elements` populated (`heading`, `paragraph`, `table`, `image`, `code`, or `metadata`); preserve layout/table/page metadata when the engine exposes it; return warnings instead of silently dropping partial-parse issues; include a fake-engine or fixture-based test path so tests don't need the real parsing library installed.

## Model adapters

Location: `packages/harborrag-adapters/src/harborrag_adapters/models/{chat,embedding,reranker}/`

Contracts (`base.py` in each subfolder):

```python
# models/chat/base.py      -> BaseChatModel
def respond(self, messages: str) -> ChatResponse: ...

# models/embedding/base.py -> BaseEmbeddingModel
def embed(self, texts: Sequence[str]) -> EmbeddingResponse: ...

# models/reranker/base.py  -> BaseReranker
def rerank(self, query: str, documents: Sequence[str], top_k: int | None = None) -> list[RerankScore]: ...
```

`MockEmbeddingModel` derives a deterministic vector from a SHA-256 digest of the text; `MockReranker` scores by token overlap. A real provider adapter (OpenAI, Bedrock, a local model server) should translate Harbor's plain-text/`Sequence[str]` inputs into the provider's native request shape, redact secrets from any diagnostics (`harborrag_core.security.redaction.redact_secrets`), and never leak raw provider payloads unless diagnostic mode is explicitly enabled.

## Repositories

Location: `packages/harborrag-adapters/src/harborrag_adapters/repositories/{vector,graph,cache,object_store,database}/`

Use `repositories/`, never `stores/` — this is enforced by review convention (see `.coderabbit.yaml`), not currently by an automated check.

Contracts:

```python
# repositories/vector/base.py -> BaseVectorRepository
def upsert(self, items: Sequence[dict[str, Any]]) -> None: ...
def search(self, vector: Sequence[float], top_k: int = 10) -> list[RetrievalResult]: ...

# repositories/graph/base.py -> BaseGraphRepository
def upsert_graph_hints(self, hints: Sequence[GraphHint]) -> None: ...

# repositories/cache/base.py -> BaseCacheRepository
def get(self, key: str) -> Any | None: ...
def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None: ...

# repositories/object_store/base.py -> BaseObjectRepository
def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> str: ...
def get_bytes(self, key: str) -> bytes: ...

# repositories/database/base.py -> BaseDatabaseRepository
def execute(self, statement: str, parameters: Sequence[Any] | None = None) -> list[dict[str, Any]]: ...
```

Real implementations, matching [deploy/](../deployment/README.md)'s stack:

```text
repositories/vector/qdrant.py
repositories/graph/neo4j.py       # or falkordb.py — see deploy/falkordb/README.md
repositories/cache/redis.py
repositories/object_store/s3.py
repositories/database/postgresql.py
```

Requirements: keep raw provider responses out of public results by default; expose capability metadata (`harborrag_core.contracts.capabilities.CapabilityProfile`) so callers can check what a provider supports before calling it; add mock/fake-client tests for request/response normalization rather than requiring a live database in the default suite.

## Engine stages

Location: `packages/harborrag-engine/src/harborrag_engine/{ingestion,retrieval,indexing,graph}/`

The ingestion (`BaseDocumentNormalizer`, `BaseChunker`, `BaseIngestionPipeline`) and retrieval (`BaseRetrievalPipeline`, `BaseEvidenceBuilder`) contracts are already implemented by mocks in `ingestion/mock.py` and `retrieval/mock.py`. A real chunker (section-aware, token-budget-aware) or a real retrieval pipeline (hybrid dense+sparse, using `retrieval/fusion.py`'s `reciprocal_rank_fusion`) should call `harborrag-core` ports and `harborrag-adapters` base classes — never a concrete provider class directly.

## Runtime services

Location: `packages/harborrag-runtime/src/harborrag_runtime/{jobs,scheduling,supervision,services}/`

`BaseJobStore`, `BaseScheduler`, `BaseSupervisor`, and `BaseRuntimeService` each have a `Mock*` counterpart today. A durable job store (SQLite/PostgreSQL/MongoDB/Redis) needs optimistic-concurrency checks so concurrent workers cannot overwrite each other's state; a real scheduler needs missed-run handling. Optional Temporal integration belongs in `runtime/temporal/`, kept behind this package's own extras so `harborrag-core`, `harborrag-adapters`, and `harborrag-engine` never depend on Temporal.

## App and MCP surfaces

`harborrag-app` (`cli/`, `api/`) and `harborrag-mcp` (`tools/`, `server/`) should only call `BaseAppService` / `BaseRuntimeService` — never adapters or provider clients directly. When adding a real CLI subcommand or HTTP route, wire it through `harborrag_app.services`, not around it; when adding a real MCP tool, enforce budgets (`harborrag_mcp.policy.McpToolPolicy`) and record an audit entry (`harborrag_mcp.audit.McpAuditLog`) before returning results.

## TODO comment style

Every stub in this repository carries a TODO that tells the next implementer exactly what to build:

```python
# TODO(connectors/github): Implement pagination and rate-limit handling for GitHub REST responses.
# TODO(parsers/pdf): Preserve table bounding boxes when the selected engine exposes layout coordinates.
# TODO(repositories/vector): Normalize provider-specific scores into HarborRAG retrieval scores.
```

Avoid vague placeholders such as `TODO(later)` or `TODO(next)` — they don't tell the next person what to do. `scripts/generate_provider_matrix.py` collects every `TODO(scope): ...` comment across the packages so you can see open work at a glance:

```bash
python scripts/generate_provider_matrix.py
```

## Before opening a PR

```bash
make lint
make typecheck
make test
make coverage
make compile
make deps-check
```

See [Testing](../testing/README.md) for what these gates check, and the root [CONTRIBUTING.md](../../CONTRIBUTING.md) for commit style and the PR checklist.
