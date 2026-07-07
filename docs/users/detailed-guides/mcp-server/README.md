# MCP Mock Tools

`harborrag-mcp` exposes the [Model Context Protocol](https://modelcontextprotocol.io/) as an audited tool facade. Today it ships two deterministic mock tools; there is no hybrid search, hierarchy navigation, or attachment analysis implemented yet.

## Tools

Defined in `packages/harborrag-mcp/src/harborrag_mcp/tools/mock.py`:

| Tool | Input schema | Returns |
|---|---|---|
| `harbor_health_check` | `{"type": "object"}` | `{"ok": true, "diagnostics": {...}}` — the same diagnostics as `harbor doctor`. |
| `harbor_sample_retrieve` | `{"query": string}` | `{"ok": true, "results": [...]}` — results from a fixed, single-entry `MockRetrievalPipeline` scored by term overlap. |

Each tool declares an `McpToolSpec(name, description, input_schema)` and implements `call(arguments)`; `MockMcpServer` (`server/mock.py`) dispatches `call_tool(name, arguments)` to whichever tool's spec name matches, raising `ValueError` for an unknown tool name.

## Policy and audit

- `harborrag_mcp.policy.McpToolPolicy` — `max_results` (default 20) and `allow_ingestion` (default `False`); `check_results(count)` raises if a tool tries to return more than the budget.
- `harborrag_mcp.audit.McpAuditLog` — `record(tool)` appends an entry; nothing calls it automatically yet, so a real tool implementation should call it before returning results.

Neither is currently wired into `MockMcpServer.call_tool()` — enforcing them end to end is part of implementing a real MCP tool (see [Extending HarborRAG](../../../developers/extending/README.md#app-and-mcp-surfaces)).

## Related

- [Setup & Integration](setup-and-integration.md) — calling these tools from Python or wiring an MCP client.
- [Architecture Overview](../../../developers/architecture/README.md#harborrag-mcp-audited-agent-tools) — how `harborrag-mcp` fits into the package structure.
