"""SQLAlchemy models of the control-plane tables.

Every tenant-owned row takes its ``tenant_id`` from the writer, so no
``tenant_id`` column has a default. IDs are TEXT, payloads are JSON (JSONB on
Postgres), datetimes are timezone-aware UTC, and constraint names come from
``NAMING_CONVENTION`` so Alembic autogenerate stays deterministic.

The sibling ``schemas_*`` modules are imported after ``Base`` and
``JSONVariant`` exist, so their models register on ``Base.metadata`` whenever
this module is imported. Alembic autogenerate and the metadata-drift test rely
on that.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.schema import conv

from harborrag_adapters.repositories.backends.sqlalchemy import UTCDateTime

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

JSONVariant = sa.JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    """Declarative base bound to the control-plane naming convention."""

    metadata = sa.MetaData(naming_convention=NAMING_CONVENTION)


class ProjectRow(Base):
    """projects: top-level grouping owning a vector collection (plan §5.1)."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    description: Mapped[str] = mapped_column(sa.Text, default="", nullable=False)
    collection: Mapped[str] = mapped_column(sa.Text, nullable=False)
    status: Mapped[str] = mapped_column(sa.Text, default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    documents: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    chunks: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    size_bytes: Mapped[int] = mapped_column(sa.BigInteger, default=0, nullable=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    version: Mapped[int] = mapped_column(sa.Integer, default=1, server_default="1", nullable=False)


class SourceRow(Base):
    """sources: one editable connection per row; credentials store secret refs only."""

    __tablename__ = "sources"
    __table_args__ = (
        sa.UniqueConstraint(
            "tenant_id", "project_id", "connection_id", name="uq_sources_connection"
        ),
        sa.UniqueConstraint("tenant_id", "source_key", name="uq_sources_source_key"),
    )

    id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(
        sa.Text, sa.ForeignKey("projects.id"), nullable=False, index=True
    )
    connection_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    source_key: Mapped[str] = mapped_column(sa.Text, nullable=False)
    source_type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    credentials: Mapped[dict[str, Any]] = mapped_column(JSONVariant, default=dict, nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONVariant, default=dict, nullable=False)
    tuning: Mapped[dict[str, Any]] = mapped_column(JSONVariant, default=dict, nullable=False)
    secret_refs: Mapped[list[str]] = mapped_column(JSONVariant, default=list, nullable=False)
    schedule: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    status: Mapped[str] = mapped_column(sa.Text, default="active", nullable=False)
    status_detail: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant, nullable=True)
    version: Mapped[int] = mapped_column(sa.Integer, default=1, server_default="1", nullable=False)
    created_by: Mapped[str] = mapped_column(sa.Text, nullable=False)
    updated_by: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    documents: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    chunks: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    errors: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)


class ConnectionRevisionRow(Base):
    """connection_revisions: immutable secret-free snapshots, one per fingerprint."""

    __tablename__ = "connection_revisions"

    tenant_id: Mapped[str] = mapped_column(sa.String(128), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    source_key: Mapped[str] = mapped_column(sa.Text, nullable=False)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False)
    secret_refs: Mapped[list[str]] = mapped_column(JSONVariant, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)

    __table_args__ = (
        sa.Index("ix_connection_revisions_source", "tenant_id", "source_key", "created_at"),
    )


class SecretRefRow(Base):
    """secrets: refs + provenance, plus the Fernet-encrypted value itself.

    ``tenant_id`` is part of every lookup: a ref is only resolvable by the
    tenant that stored it, so a ref that escapes its tenant reveals nothing.
    """

    __tablename__ = "secrets"

    ref: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_by: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    ciphertext: Mapped[bytes | None] = mapped_column(sa.LargeBinary, nullable=True)


class JobRow(Base):
    """jobs: queue + history rows projecting the core Job aggregate."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(sa.Text, nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(sa.Text, nullable=False, index=True)
    job_type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    status: Mapped[str] = mapped_column(sa.Text, default="queued", nullable=False, index=True)
    dry_run: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    attempts: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    event_sequence: Mapped[int] = mapped_column(
        sa.Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONVariant, default=dict, nullable=False)
    visibility_deadline: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    enqueued_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    documents_processed: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    chunks_created: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    errors: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)


class JobEventRow(Base):
    """job_events: ordered HarborEvent log per job (WS reconnect replay)."""

    __tablename__ = "job_events"

    job_id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    seq: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    trace_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONVariant, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class IngestionFailureRow(Base):
    """ingestion_failures: arch-plan §6 failure-tracking contract, verbatim."""

    __tablename__ = "ingestion_failures"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(sa.Text, nullable=False, index=True)
    source_name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    source_type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    record_id: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    chunk_id: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    stage: Mapped[str] = mapped_column(sa.Text, nullable=False)
    error_type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    error_message: Mapped[str] = mapped_column(sa.Text, nullable=False)
    retryable: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    attempt_count: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class ActivityRow(Base):
    """activity: append-only audit feed written on every mutation (plan §5.5)."""

    __tablename__ = "activity"

    id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    actor: Mapped[str] = mapped_column(sa.Text, nullable=False)
    verb: Mapped[str] = mapped_column(sa.Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    entity_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    summary: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)


class PendingControlPlaneEffectRow(Base):
    """pending_control_plane_effects: durable retry queue for follow-up effects.

    Holds secret retirement and audit logging that failed after the primary
    source write had already committed.
    """

    __tablename__ = "pending_control_plane_effects"

    id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    kind: Mapped[str] = mapped_column(sa.Text, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONVariant, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)


class SingletonLeaseRow(Base):
    """singleton_leases: leader-election lease of a singleton background job.

    One row per named lease, seeded by its migration.
    """

    __tablename__ = "singleton_leases"

    name: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    holder: Mapped[str] = mapped_column(sa.Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class ProviderRow(Base):
    """providers: model provider registry; key material via secret_ref only.

    ``updated_at`` exists so a per-tenant model catalog can be cache-validated
    by a cheap aggregate; every writer MUST refresh it on every mutation.
    """

    __tablename__ = "providers"

    id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    family: Mapped[str] = mapped_column(sa.Text, nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONVariant, default=dict, nullable=False)
    secret_ref: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class RoutingRuleRow(Base):
    """routing_rules: model routing configuration (M4 fills semantics).

    ``updated_at`` mirrors ProviderRow's: the tenant model-catalog fingerprint
    covers these rows too, so every writer MUST refresh it on every mutation.
    """

    __tablename__ = "routing_rules"

    id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    family: Mapped[str] = mapped_column(sa.Text, nullable=False)
    provider_id: Mapped[str] = mapped_column(sa.Text, sa.ForeignKey("providers.id"), nullable=False)
    rule_json: Mapped[dict[str, Any]] = mapped_column(JSONVariant, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class WorkspaceSettingsRow(Base):
    """workspace_settings: single JSON settings document (row id fixed to 1)."""

    __tablename__ = "workspace_settings"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONVariant, default=dict, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class MemberRow(Base):
    """members: auth subject -> RBAC role rows (plan §8.1)."""

    __tablename__ = "members"

    id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(sa.String(128), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(sa.Text, nullable=False, unique=True, index=True)
    role: Mapped[str] = mapped_column(sa.Text, default="reader", nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class McpQueryLogRow(Base):
    """mcp_query_log: read-side MCP telemetry written by harborrag-mcp-server."""

    __tablename__ = "mcp_query_log"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    tool: Mapped[str] = mapped_column(sa.Text, nullable=False)
    client: Mapped[str] = mapped_column(sa.Text, nullable=False)
    latency_ms: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False, index=True)


class GraphConflictRow(Base):
    """graph_conflicts: queued knowledge-graph disagreements awaiting resolution (M4 §5.5).

    v1 is record-only -- ``action`` records the caller's choice but resolving
    a conflict does not itself mutate FalkorDB.
    """

    __tablename__ = "graph_conflicts"
    __table_args__ = (
        sa.Index("ix_graph_conflicts_tenant_detected", "tenant_id", "detected_at", "id"),
    )

    id: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    conflict_type: Mapped[str] = mapped_column(sa.Text, nullable=False)
    subject_node_key: Mapped[str] = mapped_column(sa.Text, nullable=False)
    competing_node_key: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    description: Mapped[str] = mapped_column(sa.Text, nullable=False)
    status: Mapped[str] = mapped_column(sa.Text, nullable=False, server_default="open")
    action: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


from . import schemas_completion_requests as _schemas_completion_requests  # noqa: E402, F401
from . import schemas_conversation_memory as _schemas_conversation_memory  # noqa: E402, F401
from . import schemas_settings as _schemas_settings  # noqa: E402, F401
from . import schemas_usage as _schemas_usage  # noqa: E402, F401


class McpApiKeyRow(Base):
    """mcp_api_keys: hashed, tenant-bound MCP reader keys issued by the CLI.

    Only the SHA-256 of the key is stored. "Active" is never a column; it is
    ``revoked_at IS NULL AND expires_at > now()``. Revoked rows are kept as the
    audit trail of who issued and withdrew what. ``key_id`` and ``secret_hash``
    must be lowercase hex of a fixed length on every dialect: PostgreSQL checks
    a regex, SQLite (which has no ``~`` operator) checks length plus GLOB.
    ``conv()`` keeps the check names verbatim, outside the naming convention, so
    they match what migrations 0036 and 0040 create.
    """

    __tablename__ = "mcp_api_keys"

    key_id: Mapped[str] = mapped_column(sa.String(24), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    owner: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    name: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    secret_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    environment: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    created_by: Mapped[str] = mapped_column(sa.Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    revoked_by: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    __table_args__ = (
        sa.CheckConstraint("key_id ~ '^[0-9a-f]{24}$'", name=conv("ck_mcp_key_id")).ddl_if(
            dialect="postgresql"
        ),
        sa.CheckConstraint(
            "length(key_id) = 24 AND key_id NOT GLOB '*[^0-9a-f]*'", name=conv("ck_mcp_key_id")
        ).ddl_if(dialect="sqlite"),
        sa.CheckConstraint("secret_hash ~ '^[0-9a-f]{64}$'", name=conv("ck_mcp_key_hash")).ddl_if(
            dialect="postgresql"
        ),
        sa.CheckConstraint(
            "length(secret_hash) = 64 AND secret_hash NOT GLOB '*[^0-9a-f]*'",
            name=conv("ck_mcp_key_hash"),
        ).ddl_if(dialect="sqlite"),
        sa.CheckConstraint(
            "environment IN ('dev', 'staging', 'prod')", name=conv("ck_mcp_key_env")
        ),
        sa.CheckConstraint("expires_at > created_at", name=conv("ck_mcp_key_expiry")),
        sa.CheckConstraint("tenant_id <> '*'", name=conv("ck_mcp_api_keys_tenant")),
        sa.Index("ix_mcp_api_keys_tenant_owner", "tenant_id", "owner"),
    )
