# harborrag-mcp

Owns audited MCP tools and server boundary.

## Folder ownership

```text
tools/base.py + tools/mock.py
server/base.py + server/mock.py
```

## Team deliverables

- Implement MCP transport.
- Add tool input/output schemas and budgets.
- Log every tool call.
- Expose service-level tools only, never raw database/provider access.


## Package tests

Tests for this package live in:

```text
packages/harborrag-mcp/tests/
```

Run from the repository root:

```bash
pytest packages/harborrag-mcp/tests
```

Keep new tests in this folder when adding or changing behavior owned by this package.
