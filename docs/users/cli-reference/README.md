# CLI Reference

The `harbor` CLI is defined in `packages/harborrag-app/src/harborrag_app/cli/main.py` and calls `harborrag_app.services.BaseAppService` — never adapters directly.

## Available today

```bash
python -m harborrag_app.cli.main doctor [--json]
python -m harborrag_app.cli.main sample-ingest [--json]
```

| Command | Calls | Behavior |
|---|---|---|
| `doctor` | `service.health()` | Returns `{"ok": true, "diagnostics": {...}}` — engine and runtime diagnostics from `CompositionRoot.local().diagnostics()`. |
| `sample-ingest` | `service.ingest_once()` | Runs the mock ingestion pipeline once and returns `{"ok": true, "documents": [...], "summary": {...}}`. |

Both commands accept `--json` for machine-readable output; without it, the result prints as a Python dict.

Example:

```bash
$ python -m harborrag_app.cli.main doctor --json
{"diagnostics": {"engine": {"environment": "local", "max_concurrency": 4, "tenant": "default"}, "runtime": {"provider": "mock_runtime", "ready": true}}, "ok": true}
```

## Planned commands (stubbed)

`packages/harborrag-app/src/harborrag_app/cli/commands/` holds one TODO-stub module per future subcommand — these are not wired into `main.py` yet:

| Module | Intent |
|---|---|
| `doctor.py` | Move the `doctor` command here with clearer exit codes. |
| `ingest.py` | A full `ingest` command (currently `sample-ingest` is the only ingestion entry point). |
| `retrieve.py` | A `retrieve` command calling the retrieval pipeline. |
| `status.py` | Job/schedule status reporting once `harborrag-runtime`'s job store is real. |

Each stub's docstring is the implementation instruction: JSON output, clear exit codes, no direct provider imports — call the service layer.

## Related

- [Architecture Overview](../../developers/architecture/README.md#harborrag-app-cli-and-api-boundary) — how the CLI fits into the package boundaries.
- [Quick Start](../../getting-started/quick-start.md) — running these commands as part of the mock pipeline walkthrough.
