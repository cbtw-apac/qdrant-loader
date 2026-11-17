"""Add connection_revisions: the immutable snapshot each ingestion run builds from.

A run records the fingerprint of the connection it started with; workers load
the snapshot by that fingerprint, so editing a connection mid-run changes
nothing for the run already going. Rows carry their secret references so a
replaced stored secret can wait until no active run still needs it.

Revision ID: 0042
Revises: 0041

Phase: expand
Reversible: yes; the downgrade drops connection_revisions and its rows
Touches: connection_revisions (new)
Locks: none on upgrade; the downgrade takes an ACCESS EXCLUSIVE lock on connection_revisions to
       drop it
Deploy: before the application release
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None

_JSONB = sa.JSON().with_variant(JSONB(), "postgresql")
_TZDT = sa.DateTime(timezone=True)


def upgrade() -> None:
    """Create connection_revisions and its source index."""
    op.create_table(
        "connection_revisions",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("source_key", sa.Text(), nullable=False),
        sa.Column("snapshot_json", _JSONB, nullable=False),
        sa.Column("secret_refs", _JSONB, nullable=False),
        sa.Column("created_at", _TZDT, nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "fingerprint", name="pk_connection_revisions"),
    )
    op.create_index(
        "ix_connection_revisions_source",
        "connection_revisions",
        ["tenant_id", "source_key", "created_at"],
    )


def downgrade() -> None:
    """Drop connection_revisions and its source index."""
    op.drop_index("ix_connection_revisions_source", table_name="connection_revisions")
    op.drop_table("connection_revisions")
