"""Durable queue of knowledge-graph disagreements awaiting human resolution (M4 §5.5).

v1 is record-only: resolving a conflict persists the caller's chosen action
but does not itself mutate FalkorDB -- no adapter primitive exists yet to
patch a single node/relation in place.

Revision ID: 0020
Revises: 0019

Phase: expand
Reversible: yes; the downgrade drops graph_conflicts and its rows
Touches: graph_conflicts (new)
Locks: none on upgrade; the downgrade takes an ACCESS EXCLUSIVE lock on graph_conflicts to drop
       it
Deploy: before the application release
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

_INDEX_NAME = "ix_graph_conflicts_tenant_detected"


def upgrade() -> None:
    """Create graph_conflicts and its index."""
    op.create_table(
        "graph_conflicts",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False, server_default="DEFAULT"),
        sa.Column("conflict_type", sa.Text(), nullable=False),
        sa.Column("subject_node_key", sa.Text(), nullable=False),
        sa.Column("competing_node_key", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("action", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.Text(), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        _INDEX_NAME,
        "graph_conflicts",
        ["tenant_id", "detected_at", "id"],
    )


def downgrade() -> None:
    """Drop graph_conflicts and its index."""
    op.drop_index(_INDEX_NAME, table_name="graph_conflicts")
    op.drop_table("graph_conflicts")
