"""Turn source rows into editable connections.

Adds the connection identity (``connection_id``, ``source_key``), the split of
the legacy ``config_json`` into ``credentials``, ``config_json`` and ``tuning``,
an optimistic-concurrency ``version``, actor and timestamp stamps, and the
``status_detail`` that explains an ``error`` status.

Existing rows get a ``connection_id`` slugged from their name, made unique in
the project with ``-2``, ``-3``…, and ``source_key = <project_id>/<connection_id>``.
A row whose ``source_type`` is unknown keeps its data and turns ``error``.
The field layout below is frozen at this revision on purpose.

Revision ID: 0041
Revises: 0040

Phase: expand, data and contract in one revision
Reversible: partly; the downgrade folds credentials, config and tuning back into config_json and
            drops the new columns, but a paused source stays active, a jira_cloud source stays
            jira, and needs_reauth and deleting sources become error
Touches: sources; every row rewritten
Locks: ACCESS EXCLUSIVE lock on sources from the first ADD COLUMN until the migration run
       commits, so reads and writes of sources wait through the rewrite of every row, the NOT
       NULL changes and the unique constraints. SQLite copies sources.
Deploy: before the application release
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None

_TABLE = "sources"
_JSON = sa.JSON()
_JSONB = sa.JSON().with_variant(JSONB(), "postgresql")
_TZDT = sa.DateTime(timezone=True)
_NEW_REQUIRED = (
    ("connection_id", sa.Text()),
    ("source_key", sa.Text()),
    ("credentials", _JSONB),
    ("tuning", _JSONB),
    ("created_by", sa.Text()),
    ("updated_by", sa.Text()),
    ("created_at", _TZDT),
    ("updated_at", _TZDT),
)
_UNIQUE = {
    "uq_sources_connection": ["tenant_id", "project_id", "connection_id"],
    "uq_sources_source_key": ["tenant_id", "source_key"],
}
_SYSTEM_ACTOR = "system"

_SOURCE_TYPES = {
    "jira": "jira",
    "jira_cloud": "jira",
    "jira_datacenter": "jira",
    "confluence": "confluence",
    "confluence_cloud": "confluence",
    "confluence_datacenter": "confluence",
    "sharepoint": "sharepoint",
    "microsoft_sharepoint": "sharepoint",
    "sharepoint_online": "sharepoint",
    "github": "github",
    "github_repo": "github",
    "github_repository": "github",
    "local": "local_file",
    "local_file": "local_file",
    "local_files": "local_file",
    "filesystem": "local_file",
    "files": "local_file",
}
_LEGACY_PROVIDER = {"local_file": "local"}
_CREDENTIAL_FIELDS = {
    "jira": frozenset({"base_url", "email", "token", "deployment_type"}),
    "confluence": frozenset({"base_url", "email", "token", "deployment_type"}),
    "sharepoint": frozenset(
        {
            "tenant_id",
            "client_id",
            "client_secret",
            "access_token",
            "token_cache_path",
            "graph_api_url",
        }
    ),
    "github": frozenset({"token", "api_url", "web_url", "api_version"}),
    "local_file": frozenset(),
}
_CREDENTIAL_RENAMES = {
    "jira": {"token": "api_token"},
    "confluence": {"token": "api_token"},
}
_SHAREPOINT_METHODS = {"client_credentials": "app", "device_code": "oauth", "access_token": "pat"}
_SHAREPOINT_AUTH_MODES = {method: mode for mode, method in _SHAREPOINT_METHODS.items()}
_TUNING_FIELDS = frozenset(
    {"requests_per_minute", "page_size", "request_timeout_seconds", "max_retries", "backoff_factor"}
)
_UPGRADED_STATUS = {"paused": "active"}
_DOWNGRADED_STATUS = {"needs_reauth": "error", "deleting": "error"}

_SLUG_INVALID = re.compile(r"[^a-z0-9_-]+")
_SLUG_EDGES = re.compile(r"^[^a-z0-9]+|[-_]+$")
_SLUG_MAX = 63


def _sources() -> sa.TableClause:
    return sa.table(
        _TABLE,
        sa.column("id", sa.Text()),
        sa.column("tenant_id", sa.Text()),
        sa.column("project_id", sa.Text()),
        sa.column("source_type", sa.Text()),
        sa.column("name", sa.Text()),
        sa.column("config_json", _JSON),
        sa.column("status", sa.Text()),
        sa.column("connection_id", sa.Text()),
        sa.column("source_key", sa.Text()),
        sa.column("credentials", _JSONB),
        sa.column("tuning", _JSONB),
        sa.column("status_detail", _JSONB),
        sa.column("created_by", sa.Text()),
        sa.column("updated_by", sa.Text()),
        sa.column("created_at", _TZDT),
        sa.column("updated_at", _TZDT),
    )


def _slug(name: str) -> str:
    slug = _SLUG_INVALID.sub("-", name.strip().lower())
    slug = _SLUG_EDGES.sub("", slug)[:_SLUG_MAX].rstrip("-_")
    return slug or "connection"


def _unique(base: str, taken: set[str]) -> str:
    candidate, counter = base, 2
    while candidate in taken:
        suffix = f"-{counter}"
        candidate = f"{base[: _SLUG_MAX - len(suffix)]}{suffix}"
        counter += 1
    taken.add(candidate)
    return candidate


def _split(
    source_type: str, legacy: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    credential_fields = _CREDENTIAL_FIELDS[source_type]
    renames = _CREDENTIAL_RENAMES.get(source_type, {})
    credentials: dict[str, Any] = {}
    config: dict[str, Any] = {}
    tuning: dict[str, Any] = {}
    for key, value in legacy.items():
        if key == "auth_mode" and source_type == "sharepoint":
            continue
        if key in credential_fields:
            credentials[renames.get(key, key)] = value
        elif key in _TUNING_FIELDS:
            tuning[key] = value
        else:
            config[key] = value
    method = _method(source_type, legacy)
    return ({"method": method, **credentials} if method else credentials), config, tuning


def _method(source_type: str, legacy: dict[str, Any]) -> str | None:
    if source_type in {"jira", "confluence"}:
        return "api_token" if legacy.get("email") else "pat"
    if source_type == "sharepoint":
        mode = str(legacy.get("auth_mode") or "").strip().lower()
        if mode in _SHAREPOINT_METHODS:
            return _SHAREPOINT_METHODS[mode]
        return "pat" if legacy.get("access_token") else "app"
    if source_type == "github":
        return "pat" if legacy.get("token") else "none"
    return None


def _backfill(bind: sa.engine.Connection) -> None:
    sources = _sources()
    rows = bind.execute(
        sa.select(
            sources.c.id,
            sources.c.tenant_id,
            sources.c.project_id,
            sources.c.source_type,
            sources.c.name,
            sources.c.config_json,
            sources.c.status,
        ).order_by(sources.c.tenant_id, sources.c.project_id, sources.c.id)
    ).mappings()
    taken: dict[tuple[str, str], set[str]] = defaultdict(set)
    now = datetime.now(UTC)
    for row in list(rows):
        connection_id = _unique(_slug(row["name"]), taken[(row["tenant_id"], row["project_id"])])
        source_type = _SOURCE_TYPES.get(str(row["source_type"]).lower())
        legacy = dict(row["config_json"] or {})
        status = _UPGRADED_STATUS.get(row["status"], row["status"])
        detail: dict[str, Any] | None = None
        credentials: dict[str, Any] = {}
        tuning: dict[str, Any] = {}
        config = legacy
        if source_type is None:
            source_type = row["source_type"]
            status = "error"
            detail = {"errors": [{"field": "source_type", "issue": "unknown source type"}]}
        else:
            credentials, config, tuning = _split(source_type, legacy)
        bind.execute(
            sa.update(sources)
            .where(sources.c.id == row["id"])
            .values(
                connection_id=connection_id,
                source_key=f"{row['project_id']}/{connection_id}",
                source_type=source_type,
                credentials=credentials,
                config_json=config,
                tuning=tuning,
                status=status,
                status_detail=detail,
                created_by=_SYSTEM_ACTOR,
                updated_by=_SYSTEM_ACTOR,
                created_at=now,
                updated_at=now,
            )
        )


def _restore(bind: sa.engine.Connection) -> None:
    sources = _sources()
    rows = bind.execute(
        sa.select(
            sources.c.id,
            sources.c.source_type,
            sources.c.credentials,
            sources.c.config_json,
            sources.c.tuning,
            sources.c.status,
        )
    ).mappings()
    for row in list(rows):
        renames = {new: old for old, new in _CREDENTIAL_RENAMES.get(row["source_type"], {}).items()}
        stored = dict(row["credentials"] or {})
        method = stored.pop("method", None)
        credentials = {renames.get(key, key): value for key, value in stored.items()}
        if row["source_type"] == "sharepoint" and method in _SHAREPOINT_AUTH_MODES:
            credentials["auth_mode"] = _SHAREPOINT_AUTH_MODES[method]
        bind.execute(
            sa.update(sources)
            .where(sources.c.id == row["id"])
            .values(
                source_type=_LEGACY_PROVIDER.get(row["source_type"], row["source_type"]),
                config_json={**credentials, **(row["config_json"] or {}), **(row["tuning"] or {})},
                status=_DOWNGRADED_STATUS.get(row["status"], row["status"]),
            )
        )


def upgrade() -> None:
    """Add the connection columns to sources and backfill them from each stored row."""
    with op.batch_alter_table(_TABLE) as batch:
        for name, column_type in _NEW_REQUIRED:
            batch.add_column(sa.Column(name, column_type, nullable=True))
        batch.add_column(sa.Column("status_detail", _JSONB, nullable=True))
        batch.add_column(sa.Column("version", sa.Integer(), server_default="1", nullable=False))
    _backfill(op.get_bind())
    with op.batch_alter_table(_TABLE) as batch:
        for name, column_type in _NEW_REQUIRED:
            batch.alter_column(name, existing_type=column_type, nullable=False)
        for name, columns in _UNIQUE.items():
            batch.create_unique_constraint(name, columns)


def downgrade() -> None:
    """Restore each source's legacy config and drop the connection columns."""
    _restore(op.get_bind())
    with op.batch_alter_table(_TABLE) as batch:
        for name in _UNIQUE:
            batch.drop_constraint(name, type_="unique")
        for name, _column_type in reversed(_NEW_REQUIRED):
            batch.drop_column(name)
        batch.drop_column("status_detail")
        batch.drop_column("version")
