# Setup & Integration

There is no MCP transport (stdio/HTTP) implementation yet — `BaseMcpServer` only defines `list_tools()`/`call_tool()`, and `MockMcpServer` is meant to be called in-process. Wiring an IDE like Cursor or Claude Desktop to a real, running MCP server is future work; this page documents what you can do today.

## Calling tools directly

```python
from harborrag_mcp.server import MockMcpServer

server = MockMcpServer()
print(server.list_tools())
print(server.call_tool("harbor_health_check"))
print(server.call_tool("harbor_sample_retrieve", {"query": "HarborRAG"}))
```

Or via the package-level convenience functions:

```python
from harborrag_mcp.server import call_tool, list_tools

print(list_tools())
print(call_tool("harbor_sample_retrieve", query="HarborRAG"))
```

`call_tool()` accepts either a single `arguments` dict or keyword arguments, which it merges before dispatching.

## What a real integration needs

To make these tools reachable from an MCP client (Cursor, Claude Desktop, etc.), `harborrag-mcp` needs:

1. A transport implementation of `BaseMcpServer` (stdio or HTTP) that speaks the MCP wire protocol, translating `list_tools()`/`call_tool()` into MCP's `tools/list`/`tools/call` messages.
2. Real tools implementing `BaseMcpTool`, following the same pattern as `MockHealthTool`/`MockRetrieveTool` but calling `harborrag_runtime.services.BaseRuntimeService` for real data instead of returning a fixed mock result set.
3. Policy and audit enforcement wired into `call_tool()` — see [MCP Mock Tools](README.md#policy-and-audit).

See [Extending HarborRAG](../../../developers/extending/README.md#app-and-mcp-surfaces) for the base classes to implement against.

## Related

- [MCP Mock Tools](README.md) — the tool list and current policy/audit primitives.
- [Quick Start](../../../getting-started/quick-start.md) — the same calls as part of the mock pipeline walkthrough.
