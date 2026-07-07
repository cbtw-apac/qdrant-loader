# Installation

This page covers platform-specific notes and install troubleshooting. For the shortest path from zero to a running mock pipeline, use [Quick Start](quick-start.md).

## Requirements

```text
Python >= 3.12
```

HarborRAG is organized as a `uv` workspace with seven package-local `src/` projects under `packages/`. There is no single installable "harborrag" wheel to pull from PyPI yet — install from a local checkout.

## Option A — uv workspace (recommended)

[uv](https://docs.astral.sh/uv/) resolves the whole workspace and its dev extras in one step:

```bash
uv sync --all-packages --extra dev
uv run pytest
```

## Option B — pip editable installs

Install each package in dependency order, then the dev extras from the workspace root:

```bash
python -m pip install -e packages/harborrag-core
python -m pip install -e packages/harborrag-adapters
python -m pip install -e packages/harborrag-engine
python -m pip install -e packages/harborrag-runtime
python -m pip install -e packages/harborrag-app
python -m pip install -e packages/harborrag-mcp
python -m pip install -e packages/harborrag
python -m pip install -e ".[dev]"
```

`make bootstrap` (or `make install-dev`) runs the same sequence.

## Verifying the install

```bash
python -m harborrag_app.cli.main doctor --json
python scripts/run_mock_pipeline.py --json
```

Both commands should print `"ok": true` and exit 0 without any external services running — the default composition uses in-memory mocks end to end.

## Troubleshooting

- **`ModuleNotFoundError: harborrag_core`** — a package was not installed in dependency order, or your virtualenv is stale. Re-run `make bootstrap` or `uv sync --all-packages --extra dev`.
- **`uv sync` picks up stale versions** — delete `uv.lock` only if you intend to regenerate it (`uv lock`); otherwise a stale lock usually means a package's `pyproject.toml` version was bumped without a `uv lock` run.
- **Coverage gate fails locally** — `make coverage` enforces a 95% minimum (`pyproject.toml`'s `[tool.coverage.report].fail_under`). Run `make coverage` after any change under `packages/*/src`.
- **`scripts/check_dependency_direction.py` fails** — a package imported another package outside the allowed direction described in [Architecture Overview](../developers/architecture/README.md#dependency-direction). Move the shared code down to `harborrag-core`, or restructure the import.
