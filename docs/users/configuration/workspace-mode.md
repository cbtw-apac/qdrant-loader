# Workspace / Multi-Tenancy

There is no workspace-directory feature (auto-discovered config files, per-project log/metrics folders) in the current codebase. What exists today is a small set of tenant-scoping primitives in `harborrag-core`, which any future workspace or multi-project feature would build on.

## `Tenant`

`packages/harborrag-core/src/harborrag_core/domain/tenant.py`:

```python
@dataclass(frozen=True, slots=True)
class Tenant:
    id: str = "default"
```

Validated in `__post_init__`: `id` must be non-empty and contain no whitespace.

## `RequestContext`

`packages/harborrag-core/src/harborrag_core/execution/context.py`:

```python
@dataclass(frozen=True, slots=True)
class RequestContext:
    trace_id: str = field(default_factory=lambda: uuid4().hex)
    tenant: Tenant = field(default_factory=Tenant)
    deadline_seconds: float | None = None
```

`RequestContext` is meant to be threaded through a call chain — `.child()` derives a new context that keeps the same `trace_id` and `tenant` while allowing a narrower `deadline_seconds`. Nothing in the current mock pipeline constructs or threads a `RequestContext` yet; it's a contract for orchestration code (engine/runtime) to adopt as real providers are added.

## `EngineConfig.tenant`

The closest thing to workspace selection today is `EngineConfig.tenant` (see [Configuration Reference](config-file-reference.md)) — a single string, defaulting to `"default"`, surfaced in `harbor doctor`'s diagnostics output. It is not yet connected to `Tenant`/`RequestContext`.

## What's planned

A real workspace/multi-tenant feature would need: a `Tenant`-scoped `RequestContext` threaded through ingestion and retrieval calls, tenant-aware repository keys (e.g. per-tenant vector collections), and a budget check (`harborrag_core.execution.budgets.CapabilityBudget`) enforced per tenant. None of that exists yet — see [Extending HarborRAG](../../developers/extending/README.md) for where this kind of orchestration logic belongs.

## Related

- [Architecture Overview](../../developers/architecture/README.md#execution-request-scoped-budgets-and-deadlines) — `RequestContext`, `Deadline`, and `CapabilityBudget` together.
- [Configuration Reference](config-file-reference.md) — `EngineConfig`/`EnginePolicy`.
