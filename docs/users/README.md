# User Documentation

If you're new, start with the [Quick Start](../getting-started/quick-start.md).

HarborRAG's current user-facing surfaces are the `harbor` CLI and the MCP mock tools:

- [CLI Reference](cli-reference/README.md) — `harbor doctor` and `harbor sample-ingest`, plus the stubbed future subcommands.
- [Configuration](configuration/README.md) — `EngineConfig`/`EnginePolicy`, and the `Tenant`/`RequestContext` multi-tenancy primitives.
- [MCP Mock Tools](detailed-guides/mcp-server/README.md) — the audited agent-tool facade and how to call it.
- [Troubleshooting](troubleshooting/README.md) — install, CLI, and quality-gate issues.

There are no data-source connectors, file-conversion parsers, or hybrid search features implemented yet — see [What is HarborRAG?](../getting-started/what-is-harborrag.md) for the project's current status and [Extending HarborRAG](../developers/extending/README.md) for how to add one.
