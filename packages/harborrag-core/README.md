# harborrag-core

Owns provider-neutral domain models, protocol contracts, execution primitives, observability sinks, and security helpers.

## Team deliverables

- Add only stable, dependency-light contracts here.
- Keep provider SDKs out of this package.
- Add Protocols in `harborrag_core.ports.*` when engine code needs a new capability.
- Add domain models in `harborrag_core.domain.*` only when multiple packages need them.

## Rule

`harborrag-core` must never import adapters, engine, runtime, app, MCP, or the meta-package.


## Package tests

Tests for this package live in:

```text
packages/harborrag-core/tests/
```

Run from the repository root:

```bash
pytest packages/harborrag-core/tests
```

Keep new tests in this folder when adding or changing behavior owned by this package.
