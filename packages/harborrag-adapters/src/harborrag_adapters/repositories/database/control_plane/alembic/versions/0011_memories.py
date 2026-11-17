"""Add the canonical scope-aware long-term memory store.

Revision ID: 0011
Revises: 0010

Phase: expand
Reversible: yes; the downgrade drops memories and its rows
Touches: memories (new)
Locks: none on upgrade; the downgrade takes an ACCESS EXCLUSIVE lock on memories to drop it
Deploy: before the application release
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

_JSON = sa.JSON()
_IX_SCOPE = "ix_memories_scope"
_IX_TYPE = "ix_memories_memory_type"
_IX_TENANT = "ix_memories_tenant_id"
_IX_OWNER = "ix_memories_owner"


def upgrade() -> None:
    """Create the memories table and its indexes."""
    op.create_table(
        "memories",
        sa.Column("memory_id", sa.String(length=128), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("memory_type", sa.String(length=32), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("project_id", sa.String(length=128), nullable=True),
        sa.Column("principal_id", sa.String(length=512), nullable=True),
        sa.Column("session_id", sa.String(length=128), nullable=True),
        sa.Column("run_id", sa.String(length=128), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata_json", _JSON, nullable=False),
        sa.Column("importance", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("memory_id", name=op.f("pk_memories")),
    )
    op.create_index(_IX_SCOPE, "memories", ["scope"])
    op.create_index(_IX_TYPE, "memories", ["memory_type"])
    op.create_index(_IX_TENANT, "memories", ["tenant_id"])
    op.create_index(
        _IX_OWNER,
        "memories",
        ["tenant_id", "project_id", "principal_id", "session_id", "run_id"],
    )


def downgrade() -> None:
    """Drop the memories table and its indexes."""
    op.drop_index(_IX_OWNER, table_name="memories")
    op.drop_index(_IX_TENANT, table_name="memories")
    op.drop_index(_IX_TYPE, table_name="memories")
    op.drop_index(_IX_SCOPE, table_name="memories")
    op.drop_table("memories")
