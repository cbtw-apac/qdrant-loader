# Incremental Ingestion & Resuming Interrupted Runs

QDrant Loader is designed so that re-running `ingest` never starts from zero: it skips documents that haven't changed, and it can pick a source back up close to where an interrupted run left off. This guide explains how that works, what to expect if a run gets interrupted, and how to reason about the behavior when troubleshooting.

## 🎯 What Gets Skipped on Re-ingestion

Every document QDrant Loader processes gets a **content hash** (derived from its content, title, and metadata) and a state record is saved once the document has been embedded and upserted into QDrant. On the next `ingest` run, each document fetched from a source is compared against its stored state:

- **Unchanged** (same content hash) → skipped entirely, no re-embedding or re-upsert.
- **New or changed** (no stored state, or a different content hash) → processed normally.
- **No longer present at the source** → marked deleted in QDrant.

This is why you can run `qdrant-loader ingest` repeatedly (e.g. on a schedule, or in CI) without worrying about wasted embedding calls for content that hasn't changed.

Implementation: [`StateChangeDetector.classify_batch`](../../../../packages/qdrant-loader/src/qdrant_loader/core/state/state_change_detector.py#L116), [`Document.calculate_content_hash`](../../../../packages/qdrant-loader/src/qdrant_loader/core/document.py#L132)

## ⏸️ What Happens When a Run Is Interrupted

If `ingest` is stopped partway through (Ctrl+C, process kill, machine restart, etc.), QDrant Loader aims to make the next run pick up cleanly rather than reprocess everything from the beginning:

- **Documents already embedded and upserted before the interruption** have their processed-state recorded as soon as each one finishes — not only once an entire internal batch completes. A restart will not re-embed or re-upsert those documents.
- **Connectors that page through large result sets** (currently JIRA) save a pagination cursor (an *ingestion checkpoint*) as they go, so a restart can resume fetching from roughly where it left off instead of re-listing every page from the start.
- **In-flight work at the exact moment of interruption** (the small batch of documents actively being embedded/upserted when the process died) may be reprocessed on the next run — this is expected and safe: re-upserting a document is idempotent, it just overwrites the same vector points.

In short: an interrupted run should cost you, at most, re-processing a small window of in-flight documents — not the whole ingestion.

Implementation: [`UpsertWorker.process_embedded_chunks`](../../../../packages/qdrant-loader/src/qdrant_loader/core/pipeline/workers/upsert_worker.py#L317) (notifies as each document finishes, rather than waiting for the whole batch), [`PipelineOrchestrator._persist_single_document_state`](../../../../packages/qdrant-loader/src/qdrant_loader/core/pipeline/orchestrator.py#L763), [`CheckpointManager`](../../../../packages/qdrant-loader/src/qdrant_loader/core/state/checkpoint_manager.py#L53)

## 🔁 Forcing a Full Re-ingestion

If you need every document reprocessed regardless of its stored state (for example, after changing chunking or embedding settings), use `--force`:

```bash
qdrant-loader ingest --workspace . --force
```

`--force` bypasses both change detection and any saved ingestion checkpoints, so every document is fetched and reprocessed from scratch.

## 🧭 Things to Know

- **A document's state write must actually succeed for it to be skipped next time.** If persisting a document's state fails (e.g. the local state database is locked or unreachable), that failure is surfaced rather than silently ignored — the affected batch is reported as failed instead of falsely reported as successful, and no checkpoint is advanced past it. You'll see this in the logs as a failed batch; re-running `ingest` will simply retry those documents.
- **Change detection is based on content, not on when you happen to run ingestion.** A pagination cursor or other connector-internal bookkeeping is never treated as part of a document's content — only the actual title, body, and content-relevant metadata affect whether a document is considered changed.
- **Deleting a document from the source** is detected on the next full scan of that source and the corresponding vectors are removed from QDrant.

## 🔧 Troubleshooting

**Symptom**: the same documents keep getting reprocessed on every run, even though nothing changed at the source.

- Confirm you're not passing `--force` (which always bypasses change detection).
- Check that the state database path (`global.state_management.database_path`, default `./state.db`) is stable across runs — if it points somewhere that gets wiped or regenerated between runs (e.g. a different workspace directory, or `--force` on `init`), stored state won't be found.
- Run with `--log-level DEBUG` and look for `Batch classification completed` log lines — they report how many documents were considered new/updated versus skipped, which helps narrow down whether the state database is being read at all versus every document genuinely looking changed.

---

**Related reading**: [Data Sources](../data-sources/) for source-specific setup, [Configuration Reference](../../configuration/) for `state_management` and other global settings.
