# Configuration

HarborRAG doesn't have a file-based configuration system yet — the two pages below document the actual configuration surface that exists in code today.

1. [Configuration Reference](config-file-reference.md) — `EngineConfig` and `EnginePolicy`, the two dataclasses that exist today.
2. [Workspace / Multi-Tenancy](workspace-mode.md) — `Tenant` and `RequestContext`, the tenant-scoping primitives a future workspace feature would build on.

## Related

- [Architecture Overview](../../developers/architecture/README.md) — where these types fit in the package structure.
