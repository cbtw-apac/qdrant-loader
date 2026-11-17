"""Durable retry queue for secret retirement / audit logging after a committed write.

A row means: the source create/update/delete it depends on already
committed, but the secondary effect's first attempt failed. The recovery
drain retries and deletes the row on success (ML2 recoverability hardening).

Revision ID: 0016
Revises: 0015

Phase: expand
Reversible: yes; the downgrade drops the table and any queued effects
Touches: pending_control_plane_effects (new)
Locks: none on upgrade; the downgrade takes an ACCESS EXCLUSIVE lock on
       pending_control_plane_effects to drop it
Deploy: before the application release
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

_JSON = sa.JSON()
_TZDT = sa.DateTime(timezone=True)


def upgrade() -> None:
    """Create pending_control_plane_effects and its created_at index."""
    op.create_table(
        "pending_control_plane_effects",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("payload_json", _JSON, nullable=False),
        sa.Column("created_at", _TZDT, nullable=False),
    )
    op.create_index(
        "ix_pending_control_plane_effects_created_at",
        "pending_control_plane_effects",
        ["created_at"],
    )


def downgrade() -> None:
    """Drop pending_control_plane_effects and its index."""
    op.drop_index(
        "ix_pending_control_plane_effects_created_at",
        table_name="pending_control_plane_effects",
    )
    op.drop_table("pending_control_plane_effects")
