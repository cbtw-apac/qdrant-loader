# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Documents are re-chunked and re-embedded on their next ingestion, and the shipped
embedding model changes, so re-ingest every source with `--force-reprocess`. Follow the
[upgrade guide](docs/users/upgrading.md) before upgrading; entries marked **Breaking** need
action.

### Added

#### harborrag-adapters

- Migration `0046` stores runtime settings overrides and an append-only revision log
- Migration `0047` stores a chat session's `project_id` and an answer's `mode`, `trace_id` and `feedback`
- Structure-aware splitting of oversized text: code at syntax boundaries, Markdown at headings and fences, prose at sentence ends
- Markdown code blocks record their language, and source code files keep their indentation and are chunked as code

#### harborrag-app

- `GET` and `PATCH /v1/admin/settings` and `GET /v1/admin/settings/schema` read and change runtime settings
- `harborrag config import` and `harborrag config export` move runtime settings through a YAML file
- `harborrag doctor` validates `config/ingestion/chunking.yaml`
- `GET /v1/admin/failures` lists failed documents with `counts` per error category, and `POST /v1/admin/failures/retry` starts one retry run per original run
- HTTP chat and `harborrag chat` rerank their passages when `retrieval.rerank` is on for the session's project, or else the tenant; `PATCH /v1/admin/settings` and `harborrag config import` accept `retrieval.rerank: true` when the model catalog has a `rerank` section, and refuse it with `422 validation_error` otherwise

#### harborrag-core

- Runtime settings registry: `retrieval.top_k`, `retrieval.rerank`, `parsing.pdf_parser`, `chunking.max_tokens`, `ingestion.concurrency` and `models.embedding`, with tenant, project and connection levels
- `RetrievalRequest.rerank` asks retrieval to rerank its passages with the model catalog's `rerank` model

#### harborrag-mcp-server

- `vector_search` reads `retrieval.top_k` at tenant level as its default `top_k`; chat reads it at the level of the session's project

#### harborrag-runtime

- Cached settings provider that reloads on Postgres `LISTEN`/`NOTIFY` and a 5-second revision poll
- The API seeds settings from `config/settings.yaml` on first start and logs `config_yaml_drift` afterwards
- Ingestion pins the run's settings and `settings_revision` at start; workers parse and chunk with them
- Chunk sizes, per-source profiles and the splitting strategy are configurable in `config/ingestion/chunking.yaml`
- **Breaking:** ingestion requires the code grammars; the worker images and the `local` and `production` installs include them
- Retrieval can rerank with the model catalog's `rerank` model: it fetches four times `top_k` passages (at most 100), keeps the first `top_k` in rerank order, and adds `rerank_score` to each result's metadata while `relevance` keeps the lane's similarity; a rerank provider error fails the retrieval

### Changed

#### harborrag-app

- **Breaking:** `GET /v1/admin/ingestions/{ingestion_id}/events` sends `run.status`, `stage.progress`, `document.failed` and `run.completed`, replacing `task.<id>.progress`, `.done` and `.control`:
  - frames carry integer ids, a `: ping` arrives every 15 s, and `Last-Event-ID` resumes the stream
  - the response opens at once, and the deadline from `api_stream_timeout_seconds` ends the stream with an `error` event `deadline_exceeded`
  - a pause or resume appears as a `run.status` with the new status (`queued`, `running`, `paused`); the final status, including a cancel, arrives in `run.completed.finish_reason`
  - reconnecting to an ended run with nothing after `Last-Event-ID` answers `204`
- **Breaking:** the chat session routes answer the explorer `Session` and `Message` shapes:
  - `POST /v1/chat/sessions` takes `title` and `project_id` (an unknown project is `422 reference_not_found`, `profile_id` is `422` until v2.1.0) and answers the `Session`; `greeting` is gone
  - `GET /v1/chat/sessions` answers `items` of `Session` with `next_cursor` and searches titles with `q`
  - `GET /v1/chat/sessions/{session_id}/messages` answers `items` of `Message` newest first, pages with `cursor` and `limit` up to 100, and leaves out answers cut short by a dropped stream
  - the routes take the tenant from `X-Tenant-Id` instead of `tenant_id`
  - new sessions get `ses_…` IDs and new messages `msg_…`; stored `session-…` sessions keep theirs
- **Breaking:** `POST /v1/chat/completions` answers on the explorer contract, with no alias for the old request or response:
  - the body takes `message`, `mode` (`classic` or `instant`; `advanced` and `auto` are `422 mode_unavailable`), `reasoning` (`off`), `project_ids` (one-off questions only), `connections`, `filters` and `stream`; the tenant comes from `X-Tenant-Id` and the key from the `Idempotency-Key` header only
  - the answer is `completion_id`, `session_id`, `trace_id`, `mode`, `answer`, `citations` (`[n]` markers numbered by first use) and `usage` with `cost_usd`
  - `prompt`, `tenant_id`, `idempotency_key`, `model`, `graph_search`, `project_id`, `outcome`, `refusal_reason`, `provider`, `provider_model`, `message`, `cost`, `latency_ms`, `retry_count`, `fallback_count` and `memory_persisted` are removed
  - leaving out `session_id` asks a one-off question that creates no session and is not stored; in a session, retrieval reads only the session project's connections at its `retrieval.top_k`, and the answer is stored with the question under `completion_id`
  - an empty project is `409 no_indexed_content` before any model call, a busy session `409 session_busy` at once, and a provider failure `503 llm_unavailable` with nothing stored
  - `instant` skips the scope-check model call and graph observation, and an out-of-scope request is an ordinary answer without citations
  - `stream: true` sends the finished answer as `response.started`, one `response.output_text.delta` and `response.completed`
- **Breaking:** `harborrag chat` prints the new answer, creates its session in the `--project` project, and refuses `--project` with `--session`
- **Breaking:** chat completion failures and accounting change:
  - `503 dependency_unavailable` when the answer cannot be stored, `503 llm_unavailable` for an empty answer, and `422` for a whitespace-only `message`
  - `usage` adds up the scope check and the answer
  - an `Idempotency-Key` stays free after a failure before any model call, store and retrieval outages included
- **Breaking:** SDK chat: `ChatExecutionOptions.session_id` is optional, `project_id` became `project_ids`, and `mode`, `connections`, `filters` and `trace_id` are new; `chat_completion()` returns the explorer body and raises the turn's errors; `chat_answer()` yields the turn's events; `validate_chat_model`, `validate_chat_project` and `validate_completion_scope` are removed
- **Breaking:** every `/v1/admin/ingestions*` route answers the explorer `Ingestion` shape and the task shape is retired, reads need role `editor` and take the tenant from `X-Tenant-Id` (`?tenant_id` is removed), pause, resume and cancel answer `200` with the run, and `retry-failures` answers `202` with the new run
- Connection tests report `error_category` `secret_unavailable` when the API cannot read a secret, and say that an `env:` secret lives in the worker's environment
- `HARBORRAG_TEMPORAL_UI_URL` and `HARBORRAG_GRAFANA_URL` fill the `links` of an ingestion run
- `POST /v1/admin/ingestions` and `harborrag source sync` refuse a connection a run would reject, with `422 validation_error` naming each failing field, instead of starting a run that fails in the worker
- The CLI recognises a checkout by `config/sources/connectors.yaml`

#### harborrag-engine

- Long code chunks keep the names of the class and function they belong to, and are searchable by them
- The `default` and `concise` chat prompts ask the model to cite sources by their `[n]` number

#### harborrag-mcp-server

- The MCP server reads `config/mcp/server.yaml` and, with the file key store, `config/mcp/keys.yaml`

#### harborrag-runtime

- **Breaking:** `config/` is organised by domain (`sources/`, `ingestion/`, `graph/`, `models/`, `mcp/`) and every default path follows; a deployment that sets each `HARBORRAG_*_CONFIG_PATH` keeps working
- **Breaking:** `config/models/models.yaml` sends chat, embedding and reranking through one LiteLLM proxy gateway and reads `HARBORRAG_URL`, `HARBORRAG_API_KEY`, `HARBORRAG_CHAT_MODEL`, `HARBORRAG_EMBED_MODEL` and `HARBORRAG_RERANKER_MODEL` instead of a provider, model and API key per family
- **Breaking:** the shipped embedding model is the gateway's, in the embedding space `harbor-cohere-embed-v4`; its vectors have the same 1536 dimensions as before, so re-ingest every source with `--force-reprocess`
- **Breaking:** model variables with the `HARBOR_CHAT_`, `HARBOR_EMBED_` and `HARBOR_MEMORY_` prefixes, such as those the model smoke tests read, are renamed `HARBORRAG_CHAT_`, `HARBORRAG_EMBED_` and `HARBORRAG_MEMORY_`
- Config YAML files hold values only; their explanations moved to the configuration pages. `config/ingestion/parsers.yaml` keeps its comments because its bytes are the parser identity

#### Deployment

- The development worker mounts `config/` read-only like the API and the MCP server, so a configuration change needs a restart, not an image rebuild
- `config/sources/schedules.yaml` and `config/mcp/keys.yaml` are git-ignored; each ships as an `.example.yaml` beside it
- The `qdrant` extra of `harborrag-adapters` requires `qdrant-client>=1.17,<1.20` (was `>=1.10,<2`); the lock stays on 1.18.0
- `config/temporal.example.yaml`, `config/models.example.yaml` and `config/harborrag.example.yaml` are removed
- `env-example/.env.models.example` sets the five model gateway variables and keeps the direct-provider and other-proxy examples commented out

### Removed

#### harborrag-adapters

- **Breaking:** GitHub, Confluence, Jira and SharePoint configs built in Python no longer read credentials from environment variables; pass them explicitly

#### harborrag-app

- **Breaking:** `harborrag init` and its scaffold templates are removed with no replacement; run the CLI from a repository checkout. Projects an earlier `init` created keep working through their `harborrag.yaml` or `--project DIR`

### Fixed

#### harborrag-adapters

- Chat history and `message_count` leave out the empty or whitespace-only assistant steps of 1.x agent turns, and migration `0047`'s downgrade waits at most 5 s for its locks on Postgres, like its upgrade

#### harborrag-app

- **Breaking:** `GET /v1/admin/settings/schema` answers `{"groups": [...]}` with a description per setting, `POST /v1/admin/failures/retry` answers `409 invalid_state` when no failure matches instead of `202` with a null `ingestion_id`, and `GET /v1/admin/failures` omits `total` unless `include_total=true`
- A connection's `stats.errors` counts the failed documents of its latest run, also after a cancel, and is `0` before any run
- A run whose Temporal workflow ended without recording it, such as one terminated in the Temporal UI, no longer blocks its connection with `409 already_running`, retry runs included: starting an ingestion, removing the connection and cancelling the run record it as `CANCELLED` or `FAILED` first
- Cancelling a retry run cancels its workflow and records the run as `cancelled`, instead of answering `503`; `pause` and `resume` on a retry run answer `409 invalid_state`
- Cancelling a running or paused run whose Temporal workflow is gone, such as one past the namespace retention, records it as `cancelled` with `error_category` `workflow_not_found`, over HTTP and with `harborrag ingest cancel`, instead of answering `503` every time; a queued run that is not a retry run still answers `503`
- `POST /v1/admin/ingestions` with an `updated_after` that has no UTC offset answers `422 validation_error` on `updated_after`, instead of `500`
- `harborrag ingest pause`, `resume` and `cancel` follow the HTTP rules: pausing a paused run, pausing or resuming a retry run, and any action on a finished run exit 1 with the `invalid_state` message and send no signal, cancelling a retry run cancels its own workflow instead of answering "task not found", and an unknown run is not found
- `harborrag retrieve` reads on the shared basis for the shared tenant (`HARBORRAG_CORPUS_ACCESS_MODE=tenant_shared`), as chat does, instead of returning no candidates

#### harborrag-runtime

- A `parsers.yaml` definition for one format, such as `docx` or `csv`, replaces only that format's engine, so the other formats of its family, such as DOC, ODT, EPUB or Excel, still parse
- Starting against a control database a newer build already migrated names both schema revisions and how to recover, instead of only "migrations failed"
- The first-start import gives a Jira or Confluence Cloud entry without its email the `api_token` method, instead of the Data Center `pat` method, so a `PUT` of the email fixes it
- Cancelling a run keeps its summary, so the run's `discovered` count no longer drops when it is cancelled
- `harborrag ingest status` of a run Temporal reports as natively paused shows `paused` instead of failing with `8 is not a valid WorkflowExecutionStatus`
- Pausing a run no longer strands it: a run and its batch are paused by signal only, not natively in Temporal, where a workflow task scheduled at the pause was never dispatched again and resume and cancel hung; the Temporal UI now shows a paused run as `Running`

#### Deployment

- The development API receives `JIRA_EMAIL`, `CONFLUENCE_EMAIL`, `MICROSOFT_TENANT_ID`, `MICROSOFT_CLIENT_ID` and `GITHUB_REPOSITORY_URL` from `env/.env.connector`, so the first-start import no longer stores the Jira, Confluence and SharePoint connections without them and with status `error`
- The SharePoint entry of `config/sources/connectors.yaml` crawls the drive with the shared file type list instead of a test folder of Markdown files

## [2.0.0a2] - 2026-10-26

Stored data is not migrated from 2.0.0a1: back up the control database and re-ingest every
source. Follow the [upgrade guide](docs/users/upgrading.md) before upgrading; entries marked
**Breaking** need action.

### Added

#### harborrag

- The `harborrag` CLI ships with every install; `harborrag[local]` adds the local-stack clients [#59]

#### harborrag-adapters

- Parsing for legacy Word `.doc` and PowerPoint `.ppt`/`.pps` files [#85]
- SharePoint connector: crawl sites, libraries, folders or selected files, with allowlists and optional site pages [#90]
- SharePoint device-code sign-in, including for the Docker worker [#90] [#99]
- Jira custom fields are filterable on issues and their attachments [#85]

#### harborrag-app

- `harborrag init` scaffolds a ready-to-run project with provider presets and data-source setup [#59]
- `harborrag ingest run` runs an ingestion in-process, without Temporal [#59]
- `harborrag doctor` checks the project, configuration and every backing store [#59] [#95]
- `harborrag auth keys` issues, lists and revokes tenant-bound MCP reader keys [#85] [#89]
- `--timeout` option for `ingest watch`, `wait` and `start --wait` [#95]
- `ingest start` takes the connector positionally, like `ingest run` [#95]
- Pause, resume and cancel actions are recorded in the run's events [#85]

#### harborrag-engine

- Placeholder graph nodes for links to sources not yet ingested, replaced once the target is published [#85]

#### harborrag-mcp-server

- `find_entities` tool to search whole entities by facet [#85]

#### harborrag-runtime

- Automatic purge of retired document versions after a configurable retention period [#85]
- Searchable entity summaries that lead to their supporting evidence [#85]
- Summary facets: filterable attributes copied from connector fields [#85]
- Configurable entity summary length [#85]

### Fixed

#### harborrag-adapters

- Corrupt or encrypted `.xls` files are reported as parser rejections [#85]
- SharePoint handles deleted items and expired tokens without failing the run [#96]
- Legacy secrets are migrated to the correct tenant [#96]

#### harborrag-app

- Interrupting or failing `ingest run` no longer leaves the run stuck [#95]
- The API no longer submits the same run twice [#95]
- `ingest pause`, `resume`, `cancel`, `status` and `watch` report correct results for finished and partial runs [#95]
- Clearer error messages that never include credentials, and faster CLI startup [#95]

#### harborrag-engine

- Retrieval works for users who can read more than 10,000 documents [#96]
- Entity search honours all filters, and facet filters are case-insensitive [#96]
- Graph reads and relation repair handle placeholder nodes and cross-scope links reliably [#96]

#### harborrag-mcp-server

- Tool output schemas are valid for MCP clients again [#85]
- `find_entities` reports unknown facets instead of returning an empty result [#96]
- A broken API key file denies access instead of revoking every key [#96]
- Over-limit `mcp.yaml` values are lowered with a warning instead of stopping the server [#96]

#### harborrag-memory

- Memory retention settings are enforced [#96]
- Memory recall works without an embedding model [#96]

#### harborrag-runtime

- Large sources no longer time out during discovery [#85]
- Pausing and resuming an ingestion no longer fails the run or loses its progress [#96]
- Re-ingesting content while its old version is being purged retries instead of failing [#96]
- A retried chat request no longer interferes with a slow response still in progress [#96]
- Summary and chat client failures no longer take down ingestion workers [#96]
- A late cancellation can no longer overwrite a completed agent run [#96]
- A warning is logged when a removed storage prefix setting is still set [#96]
- One concise log line per failed document [#95]

#### Deployment

- Removed unused variables from `env-example` [#96]

### Changed

#### harborrag-adapters

- **Breaking:** one storage namespace per tenant across Qdrant, FalkorDB and the object store; re-ingest after upgrading [#85] [#96]
- LiteParse is the default parser, and the OCR server is now opt-in [#85]
- `config/parsers.yaml` supports environment variables [#85]
- **Breaking:** SharePoint requires the `Sites.Selected` permission and limits file types by default [#90]
- SharePoint shares one rate limit across workers, skips unreadable folders, and caps retries per file [#96] [#101]
- **Breaking:** Jira custom-field filter keys handle accented names; update saved filters and re-ingest [#96]
- Local connectors reject unknown filters, and partial scans no longer retire documents [#95]

#### harborrag-app

- **Breaking:** standardized CLI exit codes; failed or partial runs now exit 1 [#95]
- In a repository checkout, ingestion uses the stack's PostgreSQL and object-store settings instead of a local SQLite database [#95] [#99]
- `auth keys` requires an up-to-date control database and reports clearer errors [#95]
- Run ids cannot be reused [#95]
- Clearer ingestion API responses when Temporal is unreachable or no longer knows a run [#95]
- Inline progress display replaces the full-screen dashboard [#59]
- Local commands no longer require Temporal to be installed [#59]
- `harborrag init` keeps existing project files [#96]
- CLI file paths resolve from the current directory [#96]

#### harborrag-engine

- Each source link is stored as a single graph edge, and duplicate attachment edges are removed [#85]
- Duplicate search results are collapsed per source instead of across the whole corpus [#85]
- Vector search results link directly to their graph nodes [#85]
- More accurate unresolved-relation counts [#85]

#### harborrag-mcp-server

- **Breaking:** graph chunk edges now point from structure to chunk, and graph traversal limits are lower [#96]
- The MCP Explorer respects each tenant's limits [#96]

#### harborrag-memory

- Project-scope memories stay within the session unless enabled, and summary prompts are bounded [#96]

#### harborrag-runtime

- Summarization is off by default [#85]
- Summaries indicate when some source documents are still missing [#85]
- Summary reads no longer lock or write data [#85]
- Faster summary updates and publication [#96]
- Retired-version cleanup starts sooner and exposes metrics [#96]
- Ingestion defaults tuned for smaller hosts [#85]
- Faster ingestion workflows, with per-document cost independent of source size [#85]
- The secrets encryption key is only required by processes that open secrets [#85]
- Failed documents report a clear error code and stage, and parser rejections are not retried [#95]
- Startup fails on mismatched embedding dimensions [#95]

#### Deployment

- MinIO uses a new image that runs as a non-root user [#85]

### Deprecated

#### harborrag-adapters

- The Confluence `max_child_pages` setting is ignored with a warning [#96]

### Removed

#### harborrag-app

- Textual ingestion dashboard [#59]

#### harborrag-mcp-server

- **Breaking:** `composed_evidence_search`, `verify_citations` and `get_document_metadata` tools; use `vector_search`, `fetch_evidence` and `get_document_context` instead [#85]

#### harborrag-memory

- Unused `HARBORRAG_MEMORY_PII_REDACTION` setting [#96]

### Security

#### harborrag-adapters

- The `.ppt` parser is protected against crafted files that expand into huge output [#96]
- SharePoint tokens are stored safely, and pre-authenticated download links are no longer kept [#96] [#98]
- Model configuration errors no longer print API keys [#98]

#### harborrag-app

- Project discovery only trusts directories owned by the current user [#59]
- Errors and logs no longer expose credentials [#95]
- Unauthenticated mode refuses non-local requests unless explicitly allowed [#98]

#### harborrag-core

- More credential field names are detected and redacted [#98]

#### harborrag-engine

- Retrieval diagnostics no longer reveal documents the caller cannot read [#96]

#### harborrag-mcp-server

- Reader keys cannot target all tenants [#85]
- In API key mode, the owner token is only accepted for single-tenant deployments [#96]
- The MCP server no longer receives the secrets encryption key [#96]

#### harborrag-memory

- Shared memories can only be deleted or replaced by their author or a user with the required role [#96]

#### harborrag-runtime

- A tenant reindex no longer touches other tenants' cleanup jobs [#98]

## [2.0.0a1] - 2026-08-27

This is the first public HarborRAG 2.0 alpha release. Python package metadata,
distribution filenames, dependency pins, and release tags use the canonical
PEP 440 version `2.0.0a1`; release tooling also accepts `2.0.0-alpha` as an
operator-facing alias.

### Added

#### harborrag

- HarborRAG 2.0: a modular, provider-agnostic RAG framework built from eight independently testable packages [#1] [#6]
- One `harborrag` install, with extras for the CLI, HTTP API, MCP server, chat, Temporal and each storage provider [#31]
- Python SDK with ingestion, retrieval, graph and chat services behind one async client [#32]

#### harborrag-adapters

- Connectors for local files, GitHub, Confluence, Jira and SharePoint, including comments and attachments [#2] [#6]
- Parsers for text, Markdown, HTML, JSON, CSV/Excel, Word, ODT, EPUB, PowerPoint, images and PDF [#2] [#9]
- Choice of PDF engines: PyMuPDF, Docling, LiteParse, MinerU or PaddleOCR [#2] [#9]
- Chat, embedding and reranking clients with configurable providers [#4]
- Storage on PostgreSQL, S3-compatible object storage, Qdrant, FalkorDB and Redis [#5] [#7]
- Confluence pages are converted into structured text and tables [#16]
- Optional attachment ingestion for Confluence and Jira [#19]
- Local file discovery reports skipped files with a reason [#14]

#### harborrag-app

- `harborrag` operator CLI [#1]
- HTTP control-plane API with authentication, role-based access, health checks and a standard error format [#7]
- Read APIs for projects, sources, activity, settings and metrics [#11]
- Ingestion and connection APIs with live progress streaming [#25] [#34]

#### harborrag-engine

- Ingestion pipeline that skips unchanged documents instead of re-parsing and re-embedding them [#12] [#22]
- Table-aware chunking [#15] [#16]
- Dense, sparse and hybrid retrieval that only cites the current version of a document [#12] [#27]
- Knowledge graph of document structure and source relationships [#12] [#38]
- Retrieval-grounded chat with streaming, and a bounded multi-turn agent [#22]

#### harborrag-mcp-server

- MCP server with `vector_search` and graph tools for triplets, paths and subgraphs [#10] [#22] [#27]

#### harborrag-memory

- Short-term and working memory for chat sessions [#22]

#### harborrag-runtime

- Durable ingestion on Temporal: survives worker restarts, retries single documents, and supports pause, resume and cancel [#12] [#24]
- Rebuild vector and graph indexes from stored content without re-crawling sources [#12]
- Temporal settings in YAML configuration [#32]

#### Deployment

- Docker Compose stack and `dev.sh` scripts to run the full stack locally [#22] [#32]

#### Documentation

- Public documentation website with interactive architecture and feature sections [#31] [#40]
- Data-lifecycle, runtime-reliability, publication and security guides [#31]

#### Development

- Pre-commit and pre-push hooks running the same quality gates as CI [#28]

### Fixed

#### harborrag-adapters

- CMYK images are converted before OCR [#37]
- Clearer errors for undecodable text files and password-protected presentations [#18] [#22]

#### harborrag-engine

- Retrieval never returns a superseded document version during a concurrent publish [#31]
- Graph subgraph search returns complete results and no longer times out on large graphs [#35]
- Jira subtasks no longer appear as a separate node from their parent issue [#33]
- The graph keeps page and issue membership separate from document structure across all connectors [#38]
- Relation filters only accept relation types the graph actually stores [#36]

#### harborrag-mcp-server

- The local MCP HTTP server works on Windows [#26]

#### harborrag-runtime

- Parsing falls back to in-process when a subprocess cannot start, instead of failing the document [#30]

#### Documentation

- Website build fixes for link checking, coverage pages, UTF-8 output and asset paths [#43] [#44] [#45] [#48]

### Changed

#### harborrag

- License changed to Apache 2.0 [#3]

### Security

#### harborrag-adapters

- Connector credentials are encrypted at rest [#25]
- Outbound requests to private or disallowed addresses are blocked [#8]

#### harborrag-app

- Every control-plane API call is limited to the caller's tenant [#23]
- Secrets are redacted from API responses and diagnostics [#8] [#11]
- Production refuses to run on the default SQLite database [#8]

#### harborrag-mcp-server

- The audit log refuses symlinks and other unsafe files [#26] [#27]

#### Deployment

- Database, MinIO and Grafana passwords must be supplied by the operator [#31]

[Unreleased]: https://github.com/cbtw-apac/HarborRAG/compare/harborrag-v2.0.0a2...HEAD
[2.0.0a2]: https://github.com/cbtw-apac/HarborRAG/compare/harborrag-v2.0.0a1...harborrag-v2.0.0a2
[2.0.0a1]: https://github.com/cbtw-apac/HarborRAG/releases/tag/harborrag-v2.0.0a1
