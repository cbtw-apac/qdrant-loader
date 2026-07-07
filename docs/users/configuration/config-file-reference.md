# Configuration Reference

There is no YAML/file-based configuration loader yet — `harborrag_runtime.composition.CompositionRoot` hard-codes the mock pipeline assembly today (see [Architecture Overview](../../developers/architecture/README.md#harborrag-runtime-composition-jobs-scheduling)). This page documents the configuration surface that actually exists in code: two small dataclasses in `harborrag-engine`.

## `EngineConfig`

`packages/harborrag-engine/src/harborrag_engine/config.py`:

```python
@dataclass(frozen=True, slots=True)
class EngineConfig:
    tenant: str = "default"
    environment: str = "local"
```

| Field | Default | Meaning |
|---|---|---|
| `tenant` | `"default"` | The tenant identifier surfaced in diagnostics; see [Workspace / Multi-Tenancy](workspace-mode.md) for the related `Tenant` domain type. |
| `environment` | `"local"` | A free-form environment label (e.g. `local`, `dev`, `prod`) surfaced in diagnostics. |

## `EnginePolicy`

`packages/harborrag-engine/src/harborrag_engine/policy.py`:

```python
@dataclass(frozen=True, slots=True)
class EnginePolicy:
    max_concurrency: int = 4
    retrieval_top_k: int = 10
```

| Field | Default | Meaning |
|---|---|---|
| `max_concurrency` | `4` | Must be `>= 1`; validated in `__post_init__`, raises `ValueError` otherwise. |
| `retrieval_top_k` | `10` | Default number of retrieval results. |

## Seeing current values

```bash
python -m harborrag_app.cli.main doctor --json
```

```json
{"diagnostics": {"engine": {"environment": "local", "max_concurrency": 4, "tenant": "default"}, "runtime": {"provider": "mock_runtime", "ready": true}}, "ok": true}
```

`EngineBuilder.diagnostics()` (`packages/harborrag-engine/src/harborrag_engine/builder.py`) is what produces the `engine` block above.

## What's planned

A configuration-driven `CompositionRoot` that validates provider names, required secrets, repository settings, and feature budgets before wiring a pipeline — see the TODO on `CompositionRoot.mock_pipeline()`. Until that lands, changing configuration means changing `EngineConfig`/`EnginePolicy` defaults or constructing them explicitly in code, not editing a YAML file.

## Related

- [Workspace / Multi-Tenancy](workspace-mode.md) — the `Tenant` and `RequestContext` primitives.
- [Extending HarborRAG](../../developers/extending/README.md) — where a real, validated configuration loader would live.
