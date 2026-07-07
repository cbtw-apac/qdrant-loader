# HarborRAG Temporal Deployment

This folder contains starter configuration for running optional Temporal-backed workers.

Use Temporal when ingestion/retrieval jobs need durable workflow history, retries, visibility, and worker scaling. The default HarborRAG runtime remains dependency-free and local-friendly.

Start local Temporal services:

```bash
scripts/deployment/temporal_up.sh
```

Files:

- `dynamicconfig/development-sql.yaml` — local development dynamic config.
- `namespaces/harborrag.json` — namespace metadata placeholder for scripted setup.
