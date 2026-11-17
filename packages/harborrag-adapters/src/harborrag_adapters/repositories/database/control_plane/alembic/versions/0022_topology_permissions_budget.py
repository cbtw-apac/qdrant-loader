"""Tenant indexing epochs, fail-closed permissions and durable spending.

Revision ID: 0022
Revises: 0021

Phase: expand
Reversible: yes; the downgrade drops the new tables with their rows and the new columns
Touches: topology_jobs, topology_accepted, topology_resolution_snapshots (new columns with
         defaults); nine new topology tables
Locks: ACCESS EXCLUSIVE lock on each of the three altered tables, taken by the ALTER and held
       until the migration run commits. On SQLite the downgrade copies each table, so its write
       lock grows with table size.
Deploy: before the application release
"""

from alembic import op
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    text,
)

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None
METADATA = MetaData()

INDEXING_CONFIGS = Table(
    "topology_indexing_configs",
    METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("epoch", Integer, nullable=False),
    Column("enabled", Boolean, nullable=False),
    Column("prohibited", Boolean, nullable=False),
    Column("spending_paused", Boolean, nullable=False),
    Column("config", JSON, nullable=False),
)
PERMISSION_SNAPSHOTS = Table(
    "topology_permission_snapshots",
    METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("resource_kind", String(32), primary_key=True),
    Column("resource_id", String(128), primary_key=True),
    Column("revision", String(128), nullable=False),
    Column("known", Boolean, nullable=False),
    Column("processing_allowed", Boolean, nullable=False),
    Column("public", Boolean, nullable=False),
    Column("resolved_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("snapshot", JSON, nullable=False),
)
PERMISSION_GRANTS = Table(
    "topology_permission_grants",
    METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("resource_kind", String(32), primary_key=True),
    Column("resource_id", String(128), primary_key=True),
    Column("principal_id", String(255), primary_key=True),
    Column("allowed", Boolean, nullable=False),
    Column("denied", Boolean, nullable=False),
)
PERMISSION_HISTORY = Table(
    "topology_permission_history",
    METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("resource_kind", String(32), primary_key=True),
    Column("resource_id", String(128), primary_key=True),
    Column("revision", String(128), primary_key=True),
    Column("snapshot", JSON, nullable=False),
)
BUILD_PERMISSIONS = Table(
    "topology_build_permissions",
    METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("build_id", String(128), primary_key=True),
    Column("resource_kind", String(32), primary_key=True),
    Column("resource_id", String(128), primary_key=True),
    Column("revision", String(128), nullable=False),
)
BUILD_DOCUMENTS = Table(
    "topology_build_documents",
    METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("build_id", String(128), primary_key=True),
    Column("document_id", String(128), primary_key=True),
    Column("document_version_id", String(128), nullable=False),
)
BUDGET_DAYS = Table(
    "topology_budget_days",
    METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("day", String(10), primary_key=True),
    Column("tokens", BigInteger, nullable=False),
    Column("cost_microusd", BigInteger, nullable=False),
)
BUDGET_RESERVATIONS = Table(
    "topology_budget_reservations",
    METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("reservation_id", String(128), primary_key=True),
    Column("job_id", String(128), nullable=False),
    Column("fence", Integer, nullable=False),
    Column("day", String(10), nullable=False),
    Column("state", String(32), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("tokens", BigInteger, nullable=False),
    Column("cost_microusd", BigInteger, nullable=False),
    Column("operation_key", String(128), nullable=True),
    Column("provider_calls", Integer, nullable=False),
    Column("reservation", JSON, nullable=False),
    Column("request", JSON, nullable=False),
    Column("settlement", JSON, nullable=True),
)
DERIVED_ARTIFACTS = Table(
    "topology_derived_artifacts",
    METADATA,
    Column("tenant_id", String(128), primary_key=True),
    Column("artifact_id", String(128), primary_key=True),
    Column("build_id", String(128), nullable=False),
    Column("artifact_kind", String(32), nullable=False),
    Column("lineage", JSON, nullable=False),
    Column("artifact", JSON, nullable=False),
)

Index(
    "ix_topology_budget_live",
    BUDGET_RESERVATIONS.c.tenant_id,
    BUDGET_RESERVATIONS.c.state,
    BUDGET_RESERVATIONS.c.expires_at,
)
Index(
    "ix_topology_budget_operation",
    BUDGET_RESERVATIONS.c.tenant_id,
    BUDGET_RESERVATIONS.c.operation_key,
    BUDGET_RESERVATIONS.c.job_id,
)
Index(
    "ix_topology_derived_build",
    DERIVED_ARTIFACTS.c.tenant_id,
    DERIVED_ARTIFACTS.c.build_id,
    DERIVED_ARTIFACTS.c.artifact_kind,
)


def upgrade() -> None:
    """Create the indexing, permission and budget tables and add their columns."""
    for table in METADATA.sorted_tables:
        table.create(op.get_bind())
    additions = (
        Column("config_epoch", Integer, nullable=False, server_default="0"),
        Column("permission_dependencies", JSON, nullable=False, server_default=text("'[]'")),
        Column("source_permission_revision", String(128), nullable=False, server_default=""),
        Column("document_permission_revision", String(128), nullable=False, server_default=""),
        Column("available_at", DateTime(timezone=True), nullable=True),
    )
    for column in additions:
        op.add_column("topology_jobs", column)
    op.add_column(
        "topology_accepted", Column("config_epoch", Integer, nullable=False, server_default="0")
    )
    op.add_column(
        "topology_resolution_snapshots",
        Column("proofs", JSON, nullable=False, server_default=text("'{}'")),
    )


def downgrade() -> None:
    """Drop the added columns, then the indexing, permission and budget tables."""
    with op.batch_alter_table("topology_resolution_snapshots") as batch:
        batch.drop_column("proofs")
    with op.batch_alter_table("topology_accepted") as batch:
        batch.drop_column("config_epoch")
    with op.batch_alter_table("topology_jobs") as batch:
        for name in (
            "available_at",
            "document_permission_revision",
            "source_permission_revision",
            "permission_dependencies",
            "config_epoch",
        ):
            batch.drop_column(name)
    for table in reversed(METADATA.sorted_tables):
        table.drop(op.get_bind())
