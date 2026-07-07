# Deployment

The application code (`packages/harborrag-app`, `harborrag-mcp`) currently exposes mock services only — there is nothing production-ready to deploy yet. This page documents the deployment scaffolding that exists today under `deploy/` and `scripts/deployment/`, so the stack is ready once real providers land.

## Compose stacks

Location: `deploy/compose/`

```text
docker-compose.yml               api + cli + qdrant + redis
docker-compose.dev.yml           dev variant (harborrag-dev project name), mounts packages/ live
docker-compose.prod.yml          api + qdrant + redis, production-oriented
docker-compose.database.yml      qdrant + falkordb + redis only
docker-compose.monitoring.yml    prometheus + grafana + loki
docker-compose.temporal.yml      temporal + temporal-ui + temporal-worker
docker-compose.all.yml           everything combined
```

Images referenced by the `api` and `cli` services build from `deploy/docker/Dockerfile.api` and `deploy/docker/Dockerfile.cli`. `deploy/docker/Dockerfile.temporal-worker` builds the optional Temporal worker.

## Helper scripts

Location: `scripts/deployment/`

```bash
scripts/deployment/dev_up.sh          # docker-compose.dev.yml, builds and starts
scripts/deployment/dev_down.sh        # docker-compose.dev.yml down
scripts/deployment/database_up.sh     # docker-compose.database.yml (qdrant + falkordb + redis)
scripts/deployment/monitoring_up.sh   # docker-compose.monitoring.yml
scripts/deployment/prod_up.sh         # docker-compose.prod.yml, builds and starts detached
scripts/deployment/temporal_up.sh     # docker-compose.temporal.yml, builds and starts detached
```

Every script except `database_up.sh` copies `.env.example` to `.env` if `.env` doesn't exist yet. **`.env.example` does not exist in this repository yet** — create one (matching the `HARBORRAG_*` variables referenced in `deploy/compose/docker-compose.dev.yml`, e.g. `HARBORRAG_ENV`, `HARBORRAG_QDRANT_URL`, `HARBORRAG_REDIS_URL`) before running a script that depends on it, or the copy step will fail.

## Model asset scripts

Location: `scripts/models/` — all three are TODO placeholders today:

```text
download_docling_models.py     TODO: download/prepare Docling model assets for offline PDF parsing
download_fastembed_models.py   TODO: download/prepare FastEmbed model assets for local embedding/reranking
warmup_models.py               TODO: warm configured model providers before serving traffic
```

## Storage providers

- **Qdrant** (`deploy/qdrant/`) — the recommended first vector store for the online golden path. Default local endpoint `http://localhost:6333`; the collection name should come from HarborRAG runtime configuration once that exists, not be hard-coded.
- **FalkorDB** (`deploy/falkordb/`) — an optional graph-store choice for graph expansion and cross-source linking. Add it only after the vector-only golden path is stable; it is not required for the initial milestone.
- **Redis** — used both as a cache repository target and (in `docker-compose.database.yml`) alongside FalkorDB.

## Temporal (optional)

Location: `deploy/temporal/`

Use Temporal when ingestion/retrieval jobs need durable workflow history, retries, visibility, and worker scaling. The default HarborRAG runtime stays dependency-free and local-friendly without it — see `harborrag_runtime.temporal.*`'s TODO placeholders in [Architecture Overview](../architecture/README.md#harborrag-runtime-composition-jobs-scheduling).

```bash
scripts/deployment/temporal_up.sh
```

Files: `dynamicconfig/development-sql.yaml` (local dev dynamic config), `namespaces/harborrag.json` (namespace metadata placeholder for scripted setup).

## AWS (placeholder)

Location: `deploy/aws/` — reserves infrastructure-as-code entry points (`cdk/`, `terraform/`, `step-functions/`) for a future cloud deployment path. Validate the local Docker Compose path before implementing cloud infrastructure.

## Related

- [Architecture Overview](../architecture/README.md) — the repositories (vector/graph/cache/object-store/database) this stack backs.
- [Extending HarborRAG](../extending/README.md) — implementing the repository adapters that will actually talk to Qdrant, FalkorDB, and Redis.
