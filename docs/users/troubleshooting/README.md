# Troubleshooting

HarborRAG's mock pipeline and CLI have a small enough surface that most problems fall into a few categories. There's no connector/provider-specific troubleshooting yet, since none are implemented — see [Extending HarborRAG](../../developers/extending/README.md) for adding one.

## Install and environment

| Symptom | Likely cause | Fix |
|---|---|---|
| `ModuleNotFoundError: harborrag_core` (or any `harborrag_*`) | A package wasn't installed, or installed out of dependency order | `make bootstrap` or `uv sync --all-packages --extra dev` |
| `uv sync` resolves an unexpected version | Stale `uv.lock` relative to a `pyproject.toml` change | `uv lock` to regenerate, then `uv sync` again |
| `pip install -e packages/harborrag-X` fails on a dependency | Installed out of order | Follow the exact order in [Installation](../../getting-started/installation.md#option-b-pip-editable-installs) — `core` → `adapters` → `engine` → `runtime` → `app` → `mcp` → `harborrag` |

## CLI and mock pipeline

| Symptom | Likely cause | Fix |
|---|---|---|
| `harbor doctor` returns `"ready": false` or raises | `MockRuntimeService`/`EngineBuilder` construction failed | Run with a full traceback: `python -m harborrag_app.cli.main doctor` (without `--json`) and check the composition chain in `harborrag_runtime.composition.CompositionRoot` |
| `scripts/run_mock_pipeline.py` returns zero documents | The default `MockConnector` yields exactly one document by design | This is expected for the built-in mock; to see more, construct `MockLocalTextFileConnector(root=...)` against a directory of `.md` files instead |

## Quality gates

| Symptom | Likely cause | Fix |
|---|---|---|
| `make coverage` fails below 95% | New code under `packages/*/src` added without a matching test | Add a package-local test under the same package's `tests/` folder — see [Testing](../../developers/testing/README.md) |
| `make deps-check` / `scripts/check_dependency_direction.py` fails | An import violates the one-directional package dependency graph | Check the allowed direction in [Architecture Overview](../../developers/architecture/README.md#dependency-direction) and move shared code down to `harborrag-core` instead |
| `make typecheck` fails on a new function | Missing type annotations | `mypy` runs with `disallow_untyped_defs = true`; annotate parameters and return types (test files under `packages/*/tests/` are excluded) |
| `make lint` fails | A Ruff rule violation | `ruff check . --fix` fixes most automatically; re-run `make lint` after |

## Still stuck?

Check `CHANGELOG.md` for recent changes to the area you're working in, and the base class's own docstring — every `base.py` in this repository carries a `TODO:` describing exactly what the finished implementation should do, which often clarifies what's intentionally not implemented yet versus an actual bug.
