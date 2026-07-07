# Quick Start

This walks through installing the workspace and exercising the deterministic mock pipeline — the same data flow a real connector, parser, embedder, and vector repository will run through once they exist. No external services (Qdrant, LLM providers, etc.) are required; everything below runs against in-memory mocks.

## 1. Install the workspace

```bash
uv sync --all-packages --extra dev
```

See [Installation](installation.md) for the pip-based alternative and troubleshooting.

## 2. Run the CLI doctor command

```bash
python -m harborrag_app.cli.main doctor --json
```

```json
{"diagnostics": {"engine": {"environment": "local", "max_concurrency": 4, "tenant": "default"}, "runtime": {"provider": "mock_runtime", "ready": true}}, "ok": true}
```

This confirms the runtime and engine composition (`harborrag_runtime.composition.CompositionRoot`) wires up correctly.

## 3. Run the mock ingestion + retrieval pipeline

```bash
python scripts/run_mock_pipeline.py --json
```

This connects `MockConnector` → `MockMarkdownParser` → `MockDocumentNormalizer` → `MockEmbeddingModel` → `MockVectorRepository`, then chunks and retrieves the result with `MockRetrievalPipeline`:

```json
{
  "documents": [{"id": "harbor://mock/doc", "title": "Mock Document", "source_type": "mock", "text": "..."}],
  "chunks": [{"id": "harbor://mock/doc#chunk-0", "document_id": "harbor://mock/doc", "text": "..."}],
  "retrieval": [{"id": "harbor://mock/doc#chunk-0", "text": "...", "score": 0.0, "metadata": {"document_id": "harbor://mock/doc"}}],
  "summary": {"discovered": 1, "loaded": 1, "parsed": 1, "indexed": 1}
}
```

## 4. Call the MCP mock tools

```python
from harborrag_mcp.server import MockMcpServer

server = MockMcpServer()
print(server.call_tool("harbor_health_check"))
print(server.call_tool("harbor_sample_retrieve", {"query": "HarborRAG"}))
```

See [MCP Mock Tools](../users/detailed-guides/mcp-server/README.md) for the full tool list and [Setup & Integration](../users/detailed-guides/mcp-server/setup-and-integration.md) for wiring a client to the server.

## 5. Run the test suite

```bash
pytest
pytest --cov --cov-report=term-missing
```

Every package owns its own `tests/` folder; coverage must stay at or above 95% (`make coverage`).

## Where to go next

- [What is HarborRAG?](what-is-harborrag.md) — the framework's architecture and current status.
- [Architecture Overview](../developers/architecture/README.md) — package map and dependency rules.
- [Extending HarborRAG](../developers/extending/README.md) — implement a real connector, parser, model, or repository.
- [CLI Reference](../users/cli-reference/README.md) — current and planned CLI commands.
