# Upgrading

This page lists the steps each release needs when you upgrade an existing deployment,
newest release first. The [changelog](../../CHANGELOG.md) lists everything that changed;
entries marked **Breaking** there are the ones these steps deal with. A first install
needs none of these steps: start with the [Quick Start](../getting-started/quick-start.md).

## 2.0.0a2 to 2.0.0

Connections move from `config/sources/connectors.yaml` into the control database and
are managed through the API ([Connections](connections.md)). Ingestion reads
each connection at the start of every run.

### Before you start

- Workers now read connections, revisions and stored secrets from the control
  database. Give every worker the same `HARBORRAG_CONTROL_DB_URL` and
  `HARBORRAG_SECRETS_ENCRYPTION_KEY` as the API, or point both at the same
  file with `HARBORRAG_SECRETS_ENCRYPTION_KEY_FILE`. A worker refuses to start
  without a key against a non-SQLite database. `scripts/deployment/dev.sh`
  generates a key only while no database volume exists. With a blank key and an
  existing volume, which is the case on an upgrade, it stops with
  `… already holds a database; restore the key it was written with.` Keep a backup
  of the key.
- The API applies migrations `0041`–`0047` at start-up. `0046` adds the
  runtime settings tables: the overrides and an append-only revision log
  ([Runtime settings](configuration/runtime-settings.md)). `0047` adds empty
  columns for a chat session's `project_id` and an answer's `mode`,
  `trace_id` and `feedback`; stored sessions and messages keep their IDs and
  read back with these as `null`. `0044` drops the `agent_runs` table and
  `0045` the rest of the 1.x agent traces: tool-call messages, replay records
  of agent sessions, run-scoped and working memories, and the session `kind`,
  message `run_id` and usage `surface` columns. A downgrade brings the columns
  back, with `kind` and `surface` set to `chat` and the rest empty; the
  deleted rows do not come back. Start the API before the workers.
- Upgrade the workers together with the API. The worker records the
  cancellation of a retry run, so with an older worker a retry run cancelled
  through the API ends `failed`, or stays `running` until the API next
  settles it, for example at the next start of its connection.
- Give the API the environment variables `config/sources/connectors.yaml` names, for
  example `JIRA_BASE_URL` or `LOCAL_SOURCE_PATH`. The one-time import reads
  non-secret values from the API's environment.

### Move the configuration files

`config/` now has one folder per domain. Move each file your deployment uses:

| Old path | New path |
| --- | --- |
| `config/connectors.yaml` | `config/sources/connectors.yaml` |
| `config/connectors.example.yaml` | `config/sources/connectors.example.yaml` |
| `config/schedules.yaml` | `config/sources/schedules.yaml` |
| `config/schedules.example.yaml` | `config/sources/schedules.example.yaml` |
| `config/parsers.yaml` | `config/ingestion/parsers.yaml` |
| `config/chunking.yaml` | `config/ingestion/chunking.yaml` |
| `config/topology/graph_build.yaml` | `config/graph/build.yaml` |
| `config/topology/ontologies/` | `config/graph/ontologies/` |
| `config/models.yaml` | `config/models/models.yaml` |
| `config/models.advance.example.yaml` | `config/models/models.production.example.yaml` |
| `config/mcp.yaml` | `config/mcp/server.yaml` |
| `config/mcp_keys.yaml` | `config/mcp/keys.yaml` |
| `config/mcp_keys.example.yaml` | `config/mcp/keys.example.yaml` |

`config/settings.yaml`, `config/settings.example.yaml` and `config/temporal.yaml` stay
where they are. `config/temporal.example.yaml` and `config/models.example.yaml` are
removed; [Temporal configuration](../../deploy/temporal/README.md) and
[Model configuration](configuration/model-config.md) now explain the values.
`config/harborrag.example.yaml` is removed too, with no replacement.

- A deployment that sets the path of every file it uses keeps working without moving
  anything: `HARBORRAG_CONNECTOR_CONFIG_PATH`, `HARBORRAG_SCHEDULE_CONFIG_PATH`,
  `HARBORRAG_PARSER_CONFIG_PATH`, `HARBORRAG_CHUNKING_CONFIG_PATH`,
  `HARBORRAG_GRAPH_BUILD_CONFIG_PATH`, `HARBORRAG_MODEL_CONFIG_PATH`,
  `HARBORRAG_MCP_CONFIG_PATH` and `HARBORRAG_MCP_KEYS_PATH`. The images now set the new
  paths, so a deployment that relied on their old values must move the files or set
  the variables.
- An environment file that names an old path, such as
  `HARBORRAG_MCP_CONFIG_PATH=config/mcp.yaml`, now points at a missing file. Update it.
- Some files are optional. While its path variable is unset, a missing `chunking.yaml`
  or `graph/build.yaml` means the built-in defaults, and the graph-build defaults make
  no LLM calls; a missing `mcp/server.yaml` means the packaged MCP defaults. A missing
  `schedules.yaml` always means no declared schedules. A file left at its old path is
  therefore ignored without a warning. Run `harborrag doctor` and
  `harborrag topology config validate` after the move.
- A relative `source_path` written directly in `connectors.yaml` resolves against the
  file's folder, now `config/sources/`. Add a `../` or use an absolute path.
  Environment-backed paths such as `LOCAL_SOURCE_PATH` are unaffected.
- `config/sources/schedules.yaml` and `config/mcp/keys.yaml` are git-ignored, like
  `config/settings.yaml`. Keep them in your deployment's own version control.
- The development worker now mounts the whole `config/` read-only, like the API and the
  MCP server. A configuration change needs a worker restart, not an image rebuild.

### Send the models through one gateway

**Breaking:** `config/models/models.yaml` now sends chat, embedding and reranking through
one LiteLLM proxy gateway. It reads five variables in place of a provider, a model and an
API key per family. Update `env/.env.models`, or the secret manager that injects it:

1. Remove the variables the previous catalog read for chat and embedding:
   `HARBOR_CHAT_PROVIDER`, `HARBOR_CHAT_MODEL`, `HARBOR_CHAT_API_KEY`,
   `HARBOR_EMBED_PROVIDER`, `HARBOR_EMBED_MODEL` and `HARBOR_EMBED_API_KEY`, or their
   `HARBORRAG_` forms if you already renamed them. The shipped catalog no longer reads
   `HARBORRAG_CHAT_PROVIDER`, `HARBORRAG_CHAT_API_KEY`, `HARBORRAG_EMBED_PROVIDER` or
   `HARBORRAG_EMBED_API_KEY`, and `HARBORRAG_CHAT_MODEL` and `HARBORRAG_EMBED_MODEL` now
   hold gateway model names.

2. Set the five gateway variables:

    | Variable | Value |
    | --- | --- |
    | `HARBORRAG_URL` | The gateway's base URL, without `/v1`, for example `https://gateway.example.com` |
    | `HARBORRAG_API_KEY` | The gateway's API key |
    | `HARBORRAG_CHAT_MODEL` | The gateway's name for the chat model |
    | `HARBORRAG_EMBED_MODEL` | The gateway's name for the embedding model |
    | `HARBORRAG_RERANKER_MODEL` | The gateway's name for the rerank model |

    The model values are the bare names `GET <HARBORRAG_URL>/v1/models` lists, with
    no provider prefix.

3. Rename every remaining variable with these prefixes, in `env/.env.models` and any
   other environment file, including those the memory model and the model smoke tests
   read, such as `HARBOR_CHAT_BACKEND`:

    | Old prefix | New prefix |
    | --- | --- |
    | `HARBOR_CHAT_` | `HARBORRAG_CHAT_` |
    | `HARBOR_EMBED_` | `HARBORRAG_EMBED_` |
    | `HARBOR_MEMORY_` | `HARBORRAG_MEMORY_` |

    ```bash
    sed -i -E 's/(^|[^A-Z_])HARBOR_(CHAT|EMBED|MEMORY)_/\1HARBORRAG_\2_/g' env/.env.models
    ```

    `HARBOR_SMOKE_*` and `HARBOR_GATEWAY_TENANT` keep their names.

All five gateway variables are required: while one is missing, loading the catalog
fails, for example with `environment variable HARBORRAG_URL is not set`.
`HARBORRAG_EMBEDDING_MODEL` keeps its meaning: a logical model of the catalog, such as
`primary`, not a gateway model name.

To keep calling a provider directly, keep a catalog of your own, point
`HARBORRAG_MODEL_CONFIG_PATH` at it, and keep the variables it reads, renamed as in
step 3; see [Model configuration](configuration/model-config.md).
`env-example/.env.models.example` keeps commented examples for that case.

If you added a `memory` model to the shipped catalog, point its deployment at the
gateway as `primary` is: `provider: openai_compatible`, `api_base: ${HARBORRAG_URL}`,
`api_key: ${HARBORRAG_API_KEY}`, and the gateway's name for the model in
`HARBORRAG_MEMORY_MODEL`. See
[Optional memory model](configuration/model-config.md#optional-memory-model).

#### Re-index after the embedding change

The shipped embedding model is now the gateway's, in the embedding space
`harbor-cohere-embed-v4`. Vectors written by the previous model have the same 1536
dimensions, so nothing reports an error, but retrieval quality drops without warning
until every document is embedded again. Re-ingest every source with
`--force-reprocess`, so unchanged documents are embedded again too:

```bash
harborrag ingest run <connector> --force-reprocess
```

`harborrag source sync <project>/<connection> --mode force` does the same through the
workers, by project and connection ID.

Until a source finishes, its documents are still searched with the old vectors. The
same holds whenever you change `HARBORRAG_EMBED_MODEL` later.

### What happens at the first start

The API imports `config/sources/connectors.yaml` once, when all of these hold:

- the file exists;
- the install has no projects and no connections, in any tenant;
- no earlier import was recorded.

It imports into the tenant `HARBORRAG_INGESTION_TENANT_ID` names (`DEFAULT`
unless set). An install upgraded with projects or connections already stored,
including rows carried over from the old `/api/v1/sources` routes, is not
imported: add its connections through the API or `harborrag source add`.

The import runs once. A failed import is recorded and not tried again; a project
it created that holds no connection is removed, and what it missed is added
through the API. An import stopped part way, for example by a restart, resumes
at the next start.

Each entry becomes a connection:

- The entry's key becomes the connection's `source_key`, so its documents keep
  their ids and source scopes. The key is also its `connection_id` when it is a
  valid id (lowercase letters, digits, `-` and `_`); otherwise a slug of it is.
- `settings` and `environment` values are split into credentials and config.
  Environment values are read at import time.
- `secrets: <field>_env: NAME` becomes the reference
  `{"secret_ref": "env:NAME"}`. The value stays in the worker's environment.
  Such a reference keeps working; through the API, an editor can keep it or
  replace it with a value, but cannot point a field at another variable.
- Tuning such as `requests_per_minute` and `page_size` is kept on the
  connection and shown as its `advanced` settings.
- An entry with `project_id` goes to that project; others go to `default`,
  created when missing.
- A disabled entry is skipped. An entry with a missing environment variable or
  an invalid value is imported with status `error` and its field issues; fix it
  with `PUT`. A Jira or Confluence Cloud entry keeps the `api_token` method
  without its email, so the `PUT` only adds the `email`.

The plan is logged and the import is recorded in the workspace settings. The
file is never read again: later changes go through the API. `harborrag doctor`
keeps checking the file. `harborrag ingest run` and `harborrag ingest start` run the
same import before their first submission.

### Rows from `/api/v1/sources`

Existing rows become connections. Each gets a `connection_id` slugged from its
name, made unique in its project with `-2`, `-3` and so on, and the
`source_key` `<project_id>/<connection_id>`. A `paused` row becomes `active`;
a row whose type is unknown becomes `error`.

A Jira or Confluence row without an email gets the `pat` method, which a Cloud
site cannot use: starting its ingestion answers `422` on `credentials.email`.
`PUT` the connection with `"method": "api_token"` and the `email`; the stored
token is kept.

### Behaviour that changes

#### Connections

- **SharePoint delegated sign-ins move under the HarborRAG tenant.** Without a
  `token_cache_path`, the refresh token now lives in
  `~/.harborrag/sharepoint/<harborrag-tenant>/token-<tenant>-<client>.json`
  instead of one file shared by every tenant. Sign in again with
  `scripts/deployment/dev.sh sharepoint-login` (or the `login` command with
  `--harborrag-tenant`) before the next sync; connections with an explicit
  `token_cache_path` are unaffected.
- **Connector configs built in Python take credentials only from their
  arguments.** `GitHubRepositoryConfig`, `ConfluenceSpaceConfig`,
  `JiraProjectConfig` and `SharePointSiteConfig` no longer read `GITHUB_TOKEN`,
  `CONFLUENCE_*`, `JIRA_*`, `MICROSOFT_*` or `HARBORRAG_INGESTION_TENANT_ID`
  when a value is missing. Pass each one explicitly, for example
  `token=os.environ["JIRA_TOKEN"]`. A GitHub config without a token reads
  public repositories anonymously; Jira, Confluence and SharePoint configs
  without credentials fail validation. Connections in
  `config/sources/connectors.yaml` and the control database are unaffected.
- **Configuration fingerprints change once.** Runs now check a fingerprint of
  the stored connection. Retrying the failures of a run started before the
  upgrade reports a configuration difference; start a new sync instead.
- **A change applies from the next run, on every worker, without a restart.**
  A run that is already going keeps the values it started with.
- **Editing a Jira connection's `jql` keeps its source scope**, so items the
  new query no longer matches are removed by the next full scan.
- **`GET /v1/admin/connections` lists stored connections** in the caller's
  tenant. The `source_type` for local files is `local_file`, and
  `POST /v1/admin/ingestions` starts one by its `project_id` and
  `connection_id`.
- **Request settings can be edited.** A connection's `advanced` object holds
  `requests_per_minute`, `page_size`, `request_timeout_seconds`,
  `max_retries` and `backoff_factor`; see
  [Advanced settings](connections.md#advanced-settings).
- **Every connector reads a fixed list of file types by default**: `md`,
  `markdown`, `txt`, `pdf`, `docx`, `doc`, `epub`, `odt`, `pptx`, `csv`,
  `xlsx`, `png`, `jpg`, `jpeg` and `html`. This covers Jira and Confluence
  attachments, which can now be filtered with `allowed_extensions` and
  `excluded_extensions`. A connection that does not set `allowed_extensions`
  stops reading other types, and its next full sync removes documents already
  read from them, such as source code in a GitHub repository. Set
  `"allowed_extensions": []` to keep every type, except on SharePoint, which needs
  at least one; see [File type filters](connections.md#file-type-filters).
- **Documents above 20 MiB are skipped by default.** A connection that sets
  `max_file_size_bytes` or `max_attachment_size_bytes` keeps its own value.
- **Parsers refuse oversized documents**: PDFs above 200 pages, images above
  25 megapixels, and spreadsheets above 50,000 rows or 200,000 cells. See
  [Document limits](connections.md#document-limits).
- **Connectors reach public addresses only.** A Jira or Confluence Data
  Center, GitHub Enterprise or other host on a private, loopback or link-local
  address is refused until its host name or network is listed in
  `HARBORRAG_CONNECTOR_ALLOWED_HOSTS`, in both `env/.env.connector` and
  `env/.env.api`. See [Network access](connections.md#network-access).
- **`env:` references come only from `connectors.yaml` and the CLI.** The
  HTTP API takes secret values and refuses a new `env:NAME`.
- **Local paths can be restricted.** With `HARBORRAG_LOCAL_SOURCE_ROOT` or
  `LOCAL_SOURCE_PATH` set, a `local_file` connection must stay inside it.
  Without either on the API, the API refuses new `local_file` connections;
  the CLI and `connectors.yaml` still accept them.
- **Removed:** `GET /v1/connections` and `/api/v1/sources*` answer `404`.

#### Parser configuration

- **The API checks `config/ingestion/parsers.yaml` when it starts.** An invalid
  file stops the API with a configuration error, as it stops the worker. A
  `${VARIABLE}` reference without a default must now be set for the API as
  well, which does not receive `env/.env.parser` under Compose: set it in
  `env/.env.api`, or write `${VARIABLE:-}`. Without the file the API still
  starts and logs a warning.
- **Setting values are checked when the file loads.** A value outside what a
  setting accepts fails the load. Before, such a value failed only in the
  worker, was replaced by a default, or was passed on as written, as a limit
  written as a decimal or a boolean was. This covers the PDF `profile`,
  `min_content_chars` and `max_pages`, the image `ocr_engine`, `max_pixels`,
  `timeout`, `lang`, `config` and `ocr_server_url`, and the LiteParse
  settings. Two enabled definitions for one parser family fail the load as
  well. `harborrag doctor` reports the first error in its `parsers catalog`
  check; see
  [When the file is checked](configuration/parser-config.md#when-the-file-is-checked).
- **LiteParse `extra_options` cannot repeat a setting.** Move an argument
  that has its own key, such as `num_workers`, from `extra_options` to
  `settings`.

#### CLI, dependencies and Temporal

- **`harborrag init` is removed**, with its scaffold templates and no replacement;
  the CLI has eight commands. A project directory an earlier `init` created keeps
  working through its `harborrag.yaml`, or with `--project DIR`. Set up a new
  install from a repository checkout, as the
  [Quick Start](../getting-started/quick-start.md) does. Outside a checkout or a
  project directory, every command except `doctor` stops with
  `harborrag: no project found. …`.
- **`harborrag ingest pause|resume|cancel` use the HTTP rules.** An action the
  run's status does not allow exits 1 with the `invalid_state` message and sends
  nothing to Temporal: pausing a paused run, pausing or resuming a retry run,
  and any action on a finished run. The command needs a reachable control
  database, and a run it does not hold is reported as not found; stop such a
  run in the Temporal UI.
- **`harborrag retrieve` honours the shared tenant.** With
  `HARBORRAG_CORPUS_ACCESS_MODE=tenant_shared`, retrieval for
  `HARBORRAG_CORPUS_SHARED_TENANT_ID` reads the shared corpus, as chat does;
  every other tenant stays ACL-scoped.
- **`qdrant-client` must be 1.17 to 1.19.** Installs of the `qdrant` extra
  that pinned an older client need `pip install -U "qdrant-client>=1.17,<1.20"`.
- **A paused run shows as `Running` in the Temporal UI.** HarborRAG now
  pauses a run by signal only; its own status still reads `paused`. Do not
  pause a run from the Temporal UI or CLI on Temporal 1.31.x: that native
  pause can strand the run. Native pause is safe only on Temporal 1.32 or
  later together with `temporalio` 1.35 or later.
- **Cancel runs that an earlier release paused mid-batch before you
  upgrade.** A run started before the upgrade that was paused while a batch
  was running keeps the old native pause on its later pauses, until it
  continues as new (every 25 batches by default), so pausing it again can
  still strand it. Cancel such runs before you upgrade, or clear them as
  below if one hangs.
- **Clear a run that hangs after a pause.** When resume and cancel change
  nothing, terminate the run's `harborrag-source:<ingestion_id>` workflow
  first, then its `harborrag-source-batch:<ingestion_id>:<n>` child, in the
  Temporal UI. Terminating the child first fails the run, and cancelling it
  then answers `409 invalid_state`. HarborRAG records the run as `cancelled`
  when you next cancel it or start an ingestion of its connection.

### HTTP API changes

#### Routes, errors and limits

- **Removed routes answer `404`, with no deprecated alias:** every `/api/v1/*`
  route, including `/api/v1/health`, `/api/v1/readyz` and `/api/v1/metrics`,
  and `/v1/connections`, `/v1/agent/*`, `/v1/retrieval/*`, `/v1/graph/*`,
  `/v1/memory/*`, `/v1/schedules/*`, `/v1/admin/projections/*` and
  `PATCH`/`DELETE /v1/chat/sessions/{session_id}`. MCP server tools replace
  agent and retrieval access.
- **Probes and docs moved to the root:** `/healthz`, `/readyz`, `/docs` and
  `/openapi.json`.
- **`/metrics` answers on the ops port** (`HARBORRAG_OPS_PORT`, 9465), only to
  `HARBORRAG_METRICS_SCRAPE_TOKEN`; the API image starts with
  `python -m harborrag_app.api.serve`.
- **Every error uses one catalog of codes**, such as `not_found`,
  `validation_error`, `unauthenticated` and `rate_limited`, in place of codes
  like `harbor_not_found_error`. `details` is `null`, an object, or for
  `validation_error` a list of `{field, issue}`.
- **The trace header is `X-Trace-Id`**, 32 lowercase hex characters, in place
  of `X-Request-Id`.
- **Each principal is rate-limited**: `HARBORRAG_HTTP_RATE_DEFAULT` (10) calls
  per second on `/v1`, and `HARBORRAG_HTTP_RATE_CHAT` (2) chat completions per
  second, answering `429` with `Retry-After`.
- **A credential with several tenants sends `X-Tenant-Id`** on admin routes,
  else `400 tenant_required`; a tenant it does not hold is
  `403 tenant_forbidden`.
- **Identifiers are named after what they identify**, never a bare `id`, and
  the old names are not accepted:
  - a project's `id` is `project_id`, and its `name` and `description` are
    `project_name` and `project_description` in the responses and the `PUT`
    body.
  - a connection's `ref` is `connection_ref` and its `last_ingestion.id` is
    `last_ingestion.ingestion_id`; the reader filter chips return
    `connection_ref`.
  - the started ingestion returns `ingestion_id`, its `connection` ref is
    split into `tenant_id`, `project_id` and `connection_id`, and
    `triggered_by` is `{principal_type, principal_id}`. `workflow_id` and
    `run_id` keep their names.
  - a source type's `auth_methods[].id` is `auth_method_id`, and a connection
    test's `preview.sample[].ref` is `item_ref`.
  - `GET /v1/me` returns `principal.principal_type` and
    `principal.principal_id`.
  - a chat completion returns `completion_id`.
  - a project delete refused with `409` names `details.connection_refs`, or
    `details.connection_ref` for a connection that is ingesting.

#### Ingestions and failures

- **Ingestions start at `POST /v1/admin/ingestions`** with `project_id` and
  `connection_id` in the body. `POST …/connections/{connection_id}/sync`,
  `POST /v1/ingestions` and the `sync_now` field of connection `PUT` are
  removed.
- **Ingestion runs moved to `/v1/admin/ingestions`:** `/v1/ingestions*` answers
  `404`; `{task_id}` is now `{ingestion_id}` and `/stream` is `/events`. The
  responses use the `Ingestion` shape described below.
- **The ingestion event stream uses new event names, with no alias.**
  `task.<id>.progress` and `task.<id>.done` are gone. `run.status`
  (`{status, counters}`, lowercase status; sent when a pause or resume changes
  the status, and covering `queued`, `running` and `paused`), `stage.progress`
  (`{stage, done, total}`), `document.failed` (`{document_id, stage, error_category}`) and
  `run.completed` (`{counters, finish_reason}`, where `finish_reason` is the
  final status, so a cancel arrives here) replace them, and the stream ends
  after `run.completed`. Each frame's `id` is an integer that increases;
  `task.<id>.control` events are no longer streamed. Events a run stored before
  the upgrade under the old names stay stored but are not streamed, and a run
  that ended before the upgrade gets only a `run.completed` the first time it
  is read, with no `document.failed` backfill. A reconnect to an ended run
  with nothing left after its `Last-Event-ID` answers `204`. Clients that matched
  the old names must switch to the new ones.
- **Ingestion runs answer the explorer `Ingestion` shape**, and the task shape
  (`progress`, `stage`, `source`, `submitted_at`, `message`) is retired with no
  alias. A run carries `ingestion_id`, `tenant_id`, `project_id`,
  `connection_id`, `mode`, a lowercase `status` (`queued`, `running`, `paused`,
  `succeeded`, `failed`, `cancelled`), `counters`, `error_category`,
  `triggered_by`, `settings_revision`, `workflow_id`, `run_id`, `trace_id`,
  `links`, `created_at` and `finished_at`.
- **Ingestion reads need role `editor` and send the tenant in `X-Tenant-Id`.**
  The `?tenant_id` query parameter is removed; a run in another tenant is
  `404`. The list filters are `project_id`, `connection_ref`, `status` and
  `created_after`.
- **Pause, resume and cancel answer `200` with the run** after waiting for the
  new status; an action the state does not allow is `409 invalid_state`. A
  retry run can be cancelled but not paused or resumed: `pause` and `resume`
  on it are `409 invalid_state`.
  `retry-failures` answers `202` with the new run and its `Location`.
- **Failure inbox contract:** `GET /v1/admin/failures` leaves out `total`
  unless you send `include_total=true`, instead of answering `null`.
  `POST /v1/admin/failures/retry` answers `409 invalid_state` when no
  failure matches, instead of `202` with `ingestion_id: null`.
- **Connection `stats.errors`** is the failed-document count of the latest
  run, the same number as `counters.failed` of that run, and `0` for a
  connection that never ran; it was `null` after a cancelled run.
- **New routes:** `GET /v1/admin/failures` and `POST /v1/admin/failures/retry`
  for the failure inbox; see
  [Review and retry failures](connections.md#review-and-retry-failures).
- **New settings:** `HARBORRAG_TEMPORAL_UI_URL` and `HARBORRAG_GRAFANA_URL`
  fill `links` of a run; add them to `env/.env.api`.

#### Settings schema

- `GET /v1/admin/settings/schema` answers
  `{"groups": [{"name", "title", "settings": [...]}]}` instead of a map by key.
  Each setting carries `key`, `type`, `default`, `levels`, `applies` and
  `description`, plus `min` and `max` for a bounded key and `enum` for an
  enumerated key.

#### Chat

- **Chat sessions and history answer the explorer `Session` and `Message`
  shapes, with no alias for the old ones.**
  - `POST /v1/chat/sessions` takes an optional `title` and `project_id`;
    `project_id` is fixed for the session's life. A project the tenant does
    not have is `422 reference_not_found`, and `profile_id` is
    `422 validation_error` until v2.1.0. The response is `201` with
    `session_id`, `title`, `project_id`, `profile_id`, `message_count`,
    `created_at` and `updated_at`; `greeting` is gone. An untitled session
    reads `title: ""`.
  - New sessions get `ses_…` IDs and new messages `msg_…` IDs. Stored
    `session-…` sessions keep their IDs and stay readable.
  - All three session routes take the tenant from the credential, or from
    `X-Tenant-Id` when it holds several; the `tenant_id` body field and
    `?tenant_id` query are removed.
  - `GET /v1/chat/sessions` answers `{"items": [...], "next_cursor": null}`
    instead of `{"sessions": [...]}`, adds `q` to search titles, and always
    sends `next_cursor`, `null` on the last page.
  - `GET /v1/chat/sessions/{session_id}/messages` answers
    `{"items": [...], "next_cursor": null}` **newest first**, instead of
    `{"messages": [...]}` oldest first. Page with `cursor` (was `after`) and
    `limit` 1–100 (default 20, was 50 of at most 200). Each message carries
    `message_id`, `session_id`, `role`, `content`, `mode`, `citations`,
    `trace_id`, `feedback` and `created_at`; `token_count` and `partial` are
    gone. A user message reads `mode: null`, `citations: []` and
    `trace_id: null`. Each citation carries `n`, `chunk_id`, `document_id`,
    `title`, `snippet`, `url` and `page`; a citation stored before this
    release reads back numbered by position, with an empty `snippet`.
  - An answer cut short by a dropped stream is left out of history and out of
    `message_count`, and system messages are not listed. So are the empty
    assistant steps of 1.x agent turns.
  - Another reader's session, or an unknown one, is `404 not_found`.
- **`POST /v1/chat/completions` answers the explorer completion, with no alias
  for the old request or response.**
  - The body is `message` (1 to 8,000 characters, was `prompt`), optional
    `session_id`, `mode` (`classic` by default, or `instant`), `reasoning`
    (`off` only), `project_ids`, `connections`, `filters` and `stream`.
    `tenant_id`, `idempotency_key`, `model`, `graph_search` and `project_id`
    are removed and answer `422`; `mode: "rag"` is `422`, and `advanced` or
    `auto` is `422 mode_unavailable` until v2.1.0.
  - The tenant comes from the credential, or from `X-Tenant-Id`. The
    idempotency key is the `Idempotency-Key` header only, and `session_id` is
    now part of the request it guards.
  - Leaving out `session_id` asks a one-off question: `session_id: null` in the
    answer, nothing stored, and no session created. Create sessions with
    `POST /v1/chat/sessions`; their project is the turn's scope, and
    `project_ids` in a session is `422 validation_error`. A connection outside
    the scope is `422 connection_out_of_scope`.
  - Retrieval reads only the connections of the session's project (or of the
    one-off question's `project_ids`), at that project's `retrieval.top_k`. A
    project with nothing published is `409 no_indexed_content` before any model
    call.
  - The answer is `completion_id` (the stored assistant `message_id`),
    `session_id`, `trace_id`, `mode`, `answer`, `citations` (`n`, `chunk_id`,
    `document_id`, `title`, `snippet`, `url`, `page`) and `usage` (`mode`,
    `reasoning`, `steps`, `prompt_tokens`, `completion_tokens`,
    `reasoning_tokens`, `cost_usd`). `created`, `model`, `provider`,
    `provider_model`, `message`, `outcome`, `refusal_reason`, `finish_reason`,
    `cost`, `latency_ms`, `retry_count`, `fallback_count`, `title`,
    `project_id` and `memory_persisted` are gone.
  - `usage` adds up every model call of the turn, the `classic` scope check
    included, instead of only answer generation.
  - Answers cite sources as `[n]`, numbered from 1 in order of first use,
    instead of copying `[Source N: …]` labels.
  - An out-of-scope request is an ordinary answer with no citations.
  - A provider failure, or an empty answer, is `503 llm_unavailable`, and a
    busy session is `409 session_busy` at once instead of after a 30 s wait;
    neither stores anything. The question is stored with its answer, not before
    the model call. An answer that could not be stored is not returned: the
    completion is `503 dependency_unavailable` instead of `200` with
    `memory_persisted: false`.
  - A `message` of whitespace only is `422 validation_error` on `message`.
  - An `Idempotency-Key` whose request failed before any model call (an
    outage, a refusal, a busy session) stays free for a retry; one that failed
    after is `409 invalid_state`.
  - With `stream: true`, the stream sends `response.started`, one
    `response.output_text.delta` with the whole answer, and
    `response.completed` with the JSON body, once the answer is complete. The
    `retrieval.completed`, `response.citations`, `response.warning` and
    `response.error` events are no longer sent.
- **An `Idempotency-Key` reused with another body is `422`**, not `409`; a key
  is kept for 24 hours.
- **Chat completions are retrieval chat only:** `max_steps` is removed and
  answers `422`, the `response.agent.progress` stream event is gone, and
  `HARBORRAG_API_AGENT_TOKEN_BUDGET` and `HARBORRAG_MEMORY_AGENT_TOOLS` are
  ignored. Sessions created by the 1.x agent surface stay stored and are now
  listed by `GET /v1/chat/sessions` like any chat session. Session listings
  no longer carry `kind`, stored messages no longer carry `run_id`, and the
  `tool` message role is gone.
- **`harborrag chat`** prints the new answer (`--json` prints the completion
  body), creates its session in the `--project` project, and refuses
  `--project` with `--session`.
- **SDK callers of the chat service** (`harborrag_app.workflow_control`):
  - `ChatExecutionOptions.session_id` is optional (`None` asks a one-off
    question), `project_id` is replaced by `project_ids` (one-off questions
    only), and `mode`, `connections`, `filters` and `trace_id` are new.
  - `chat_completion()` answers the explorer completion body and raises the
    turn's errors instead of returning a failed response for them; the new
    `chat_answer()` yields the turn's events (`RetrievalFound`, `AnswerDelta`,
    `TurnCompleted`).
  - `validate_chat_model`, `validate_chat_project` and
    `validate_completion_scope` are removed: the turn checks the model, the
    projects and the request's scope itself.

### Runtime settings

Six settings (`retrieval.top_k`, `retrieval.rerank`, `parsing.pdf_parser`,
`chunking.max_tokens`, `ingestion.concurrency`, `models.embedding`) can now be
changed through `/v1/admin/settings`
([Runtime settings](configuration/runtime-settings.md)). Nothing changes at
upgrade: a setting with no override keeps using the knob that governs it today
(`config/mcp/server.yaml`, `HARBORRAG_CHAT_RETRIEVAL_TOP_K`,
`config/ingestion/parsers.yaml`, `config/ingestion/chunking.yaml`,
`config/temporal.yaml`), and no document is reprocessed.

`GET /v1/admin/settings` shows the registry default for a setting with no
override, even when you changed its old knob. To carry a changed knob over,
create `config/settings.yaml` before the first start of the new API, with
only the keys whose old knob you changed and your value for each, for example
`retrieval.top_k: 8`. Do not copy `config/settings.example.yaml` whole: it
lists every key you can set at its registry default, and every key in the seed
file becomes an override that replaces its old knob, so a copied default would
pin the default over a value you changed. The API seeds the tenant
`HARBORRAG_INGESTION_TENANT_ID` names from that file once, when the tenant has
no settings revisions. Set
`HARBORRAG_SETTINGS_SEED_PATH` to read the file from another path. After the
seed, edits to the file only log a `config_yaml_drift` warning; change
settings with the API or `harborrag config import`.

The first sync after any `parsing.*` or `chunking.*` override reprocesses that
connection, because both feed the processing identity.

`retrieval.rerank: true` is accepted when the model catalog has a `rerank` section, as
the shipped catalog now does; without one it is still refused with `422`. Nothing
reranks at upgrade, because the default stays `false`. Switch it on per project or for
the tenant to rerank chat retrieval; see
[Rerank chat retrieval](configuration/runtime-settings.md#rerank-chat-retrieval).

#### Use docling for PDFs

`parsing.pdf_parser: docling` needs two things HarborRAG does not ship:

1. A `parser: pdf` definition with a single `docling` engine in
   `config/ingestion/parsers.yaml`, added with `enabled: false` so the shipped
   `pdf-liteparse` definition stays the boot default. Copy the whole
   commented `pdf-docling:` block of `config/ingestion/parsers.yaml`, from the
   `pdf-docling:` line through its `engines` list and the last docling
   setting (`max_file_size`), into the active `parsers:` section
   uncommented, and change `enabled: true` to `enabled: false`. Keep its
   `engines` list to the single `docling` entry.
2. The `pdf-docling` extra of `harborrag-adapters` installed in the worker
   image, for example `pip install "harborrag-adapters[pdf-docling]"`.

Without them, PDF documents fail with `document_release_parser_unavailable`,
recorded as retryable. Add the definition, then run `retry-failures`; the
retry replays the parser the run was pinned to.

Adding the definition reprocesses every connection once, not only the one you
switch to docling. The parser identity is the digest of the whole
`config/ingestion/parsers.yaml`, so any edit to the file changes it for every
connection, and the next sync of each connection reprocesses all of its
documents. To keep that to one reprocess:

1. Put the same `config/ingestion/parsers.yaml` in the API and in the worker before you
   set `parsing.pdf_parser: docling`. The API reads the file when it starts a
   run and the worker when it prepares a scheduled run, so with two different
   files the identity flips between the two kinds of run and documents
   reprocess on alternate syncs; docling documents also fail with
   `document_release_parser_unavailable` on a worker without the definition.
   The dev compose mounts the same `config/` into the API and the worker, so
   restart both after editing the file.
2. Then set the override.

A `retry-failures` run replays the processing identity of the run it retries.
Documents it publishes after you add the definition keep the old identity, so
the next sync reprocesses them once more.

### Not yet supported

- `item_refs` on `POST /v1/admin/ingestions` answers `501 not_supported`.
- Project ids are unique across tenants.

## 2.0.0a1 to 2.0.0a2

Alpha2 keeps each tenant's data under one storage namespace across Qdrant, FalkorDB and the
object store, and it changes how documents are projected into the graph. Stored data is not
migrated, so plan a reset and a full re-ingest.

### 1. Before you upgrade

1. Stop schedules and API submissions. Let every running HarborRAG workflow finish, or
   terminate them with the [Temporal CLI](https://docs.temporal.io/cli):

    ```bash
    temporal workflow terminate --query 'WorkflowType STARTS_WITH "harborrag"'
    ```

    An alpha1 run resumed by an alpha2 worker cannot find its plans and artifacts.

2. Back up the PostgreSQL control database. Restoring that backup, together with the
   untouched alpha1 stores, is the only practical rollback: alpha1 cannot start against a
   migrated database, and downgrading the schema loses data.

### 2. Update configuration

1. **Storage namespace.** Unset `HARBORRAG_QDRANT_COLLECTION_PREFIX` and
   `HARBORRAG_FALKORDB_TENANT_GRAPH_PREFIX`; they are ignored with a startup warning. Set
   `HARBORRAG_STORAGE_NAMESPACE_PREFIX` instead (default `harborrag`), and give each
   deployment its own value when they share stores. See
   [One tenant namespace in every store](configuration/workspace-mode.md#one-tenant-namespace-in-every-store).
2. **MCP limits.** Review `config/mcp/server.yaml`. Graph `max_depth` above 4 and `max_paths`
   above 5 are lowered with a warning.
3. **Confluence.** Remove `max_child_pages` from Confluence connectors; it is ignored with a
   warning.
4. **SharePoint.** Grant the app `Sites.Selected` on the configured sites only. A token with
   a broad role such as `Sites.Read.All` is refused at startup. Only `docx`, `pdf`, `pptx`,
   `xlsx`, `txt` and `md` files are ingested by default; set `allowed_extensions` to add
   others. For `auth_mode: device_code` on the Docker stack, rebuild the worker image, then
   run `scripts/deployment/dev.sh sharepoint-login`. See
   [SharePoint crawl scope, allowlists, and skips](configuration/connector-config.md#sharepoint-crawl-scope-allowlists-and-skips).

### 3. Clear the alpha1 data

Drop the alpha1 Qdrant collections, FalkorDB graphs and object-store keys, or keep them until
the upgrade is confirmed if you may need to roll back. Alpha2 uses these names:

| Store | Name |
| --- | --- |
| Qdrant collection | `{prefix}_{tenant}_{index}` |
| FalkorDB graph | `{prefix}_{tenant}` |
| Object-store keys | under `{prefix}_{tenant}/` |

### 4. Migrate the control database

Every HarborRAG process that opens the control database applies pending migrations at
startup. Start one process first (for example the API), wait until it is healthy, then start
the worker and the other services. The schema moves from revision 0019 to 0040; on a large
control database, migrations 0021 and 0037 hold table locks for a while.

### 5. Re-ingest

Re-ingest every source. The graph projection changed, so every document is reprocessed
without `--force-reprocess`.

Jira filter keys for custom fields with accented names have changed. Update saved filters
that use them.

### 6. Optional: keep entity summaries

Summarization is now off by default. To keep entity summaries, set `summarization.enabled`
to `true` in `config/graph/build.yaml`, then run:

```bash
harborrag topology summaries backfill
```
