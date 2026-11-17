"""Durable opt-in semantic enrichment, independent from document publication.

Revision ID: 0021
Revises: 0020

Phase: expand, data and contract in one revision
Reversible: yes; the downgrade drops the topology tables, their rows and
            document_versions.source_scope_id
Touches: document_versions (source_scope_id backfilled on every row, then NOT NULL); ten new
         topology tables
Locks: ACCESS EXCLUSIVE lock on document_versions from the ADD COLUMN until the migration run
       commits, so reads and writes wait through the backfill of every row and the NOT NULL
       change. SQLite copies document_versions.
Deploy: before the application release
"""

from alembic import op
from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, String, text

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add document_versions.source_scope_id and create the topology tables."""
    op.add_column("document_versions", Column("source_scope_id", String(128), nullable=True))
    op.execute(
        text(
            "UPDATE document_versions SET source_scope_id = "
            "(SELECT source_scope_id FROM documents WHERE documents.document_id = document_versions.document_id)"
        )
    )
    with op.batch_alter_table("document_versions") as batch:
        batch.alter_column("source_scope_id", existing_type=String(128), nullable=False)
    op.create_table(
        "topology_policies",
        Column("tenant_id", String(128), primary_key=True),
        Column("source_scope_id", String(128), primary_key=True),
        Column("enabled", Boolean, nullable=False),
        Column("revision", Integer, nullable=False),
        Column("fingerprint", String(128), nullable=False),
        Column("policy", JSON, nullable=False),
    )
    op.create_table(
        "topology_jobs",
        Column("job_id", String(128), primary_key=True),
        Column("tenant_id", String(128), nullable=False),
        Column("source_scope_id", String(128), nullable=False),
        Column("document_id", String(128), nullable=False),
        Column("document_version_id", String(128), nullable=False),
        Column("policy_revision", Integer, nullable=False),
        Column("fingerprint", String(128), nullable=False),
        Column("policy", JSON, nullable=False),
        Column("state", String(32), nullable=False),
        Column("fence", Integer, nullable=False),
        Column("attempts", Integer, nullable=False),
        Column("lease_until", DateTime(timezone=True)),
        Column("error_code", String(128)),
        Column("expected_chunks", JSON),
        Column("created_at", DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_topology_jobs_dispatch", "topology_jobs", ["tenant_id", "state"])
    op.create_table(
        "topology_checkpoints",
        Column("tenant_id", String(128), primary_key=True),
        Column("job_id", String(128), primary_key=True),
        Column("chunk_id", String(256), primary_key=True),
        Column("input_digest", String(128), nullable=False),
        Column("extraction_fingerprint", String(128), nullable=False),
        Column("checkpoint", JSON, nullable=False),
    )
    op.create_index(
        "ix_topology_checkpoint_reuse",
        "topology_checkpoints",
        ["tenant_id", "extraction_fingerprint", "input_digest"],
    )
    op.create_table(
        "topology_builds",
        Column("build_id", String(128), primary_key=True),
        Column("tenant_id", String(128), nullable=False),
        Column("job_id", String(128), nullable=False),
        Column("fence", Integer, nullable=False),
        Column("verified", Boolean, nullable=False),
        Column("manifest", JSON, nullable=False),
    )
    op.create_table(
        "topology_accepted",
        Column("tenant_id", String(128), primary_key=True),
        Column("document_id", String(128), primary_key=True),
        Column("document_version_id", String(128), nullable=False),
        Column("source_scope_id", String(128), nullable=False),
        Column("policy_revision", Integer, nullable=False),
        Column("build_id", String(128), nullable=False),
    )
    op.create_table(
        "topology_mentions",
        Column("mention_id", String(128), primary_key=True),
        Column("tenant_id", String(128), nullable=False),
        Column("build_id", String(128), nullable=False),
        Column("entity_id", String(128), nullable=False),
        Column("chunk_id", String(256), nullable=False),
        Column("label_key", String(256), nullable=False),
        Column("record", JSON, nullable=False),
    )
    op.create_index("ix_topology_mentions_label", "topology_mentions", ["tenant_id", "label_key"])
    op.create_index("ix_topology_mentions_build", "topology_mentions", ["build_id"])
    op.create_table(
        "topology_assertions",
        Column("assertion_id", String(128), primary_key=True),
        Column("tenant_id", String(128), nullable=False),
        Column("build_id", String(128), nullable=False),
        Column("subject_entity_id", String(128), nullable=False),
        Column("object_entity_id", String(128), nullable=False),
        Column("record", JSON, nullable=False),
    )
    op.create_index("ix_topology_assertions_build", "topology_assertions", ["build_id"])
    op.create_table(
        "topology_resolution_heads",
        Column("tenant_id", String(128), primary_key=True),
        Column("revision", Integer, nullable=False),
    )
    op.create_table(
        "topology_resolution_decisions",
        Column("tenant_id", String(128), primary_key=True),
        Column("decision_id", String(128), primary_key=True),
        Column("revision", Integer, nullable=False),
        Column("decision", JSON, nullable=False),
    )
    op.create_table(
        "topology_resolution_snapshots",
        Column("tenant_id", String(128), primary_key=True),
        Column("resolution_revision", String(128), primary_key=True),
        Column("mapping", JSON, nullable=False),
    )


def downgrade() -> None:
    """Drop the topology tables and document_versions.source_scope_id."""
    for name in (
        "topology_resolution_snapshots",
        "topology_resolution_decisions",
        "topology_resolution_heads",
        "topology_assertions",
        "topology_mentions",
        "topology_accepted",
        "topology_builds",
        "topology_checkpoints",
        "topology_jobs",
        "topology_policies",
    ):
        op.drop_table(name)
    with op.batch_alter_table("document_versions") as batch:
        batch.drop_column("source_scope_id")
