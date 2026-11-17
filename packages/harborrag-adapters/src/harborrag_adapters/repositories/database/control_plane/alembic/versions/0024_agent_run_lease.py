"""Add an executor lease to agent-run checkpoints.

``resume`` previously accepted any RUNNING checkpoint, so a second worker
could replay a step the still-live original was executing. The lease fences
that: the executing worker stamps ``lease_owner``/``lease_expires_at`` on
every persisted step, ``resume`` refuses a RUNNING run whose lease is live
(HarborConflictError) and claims one whose lease lapsed (the crash case).
Terminal statuses clear both columns.

Revision ID: 0024
Revises: 0023

Phase: expand
Reversible: yes; the downgrade drops the two lease columns
Touches: agent_runs; nullable columns, no backfill
Locks: ACCESS EXCLUSIVE lock on agent_runs, taken by the ALTER and held until the migration run
       commits. On SQLite the downgrade copies agent_runs, so its write lock grows with table
       size.
Deploy: before the application release
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

_TABLE = "agent_runs"


def upgrade() -> None:
    """Add the lease owner and expiry columns to agent_runs."""
    op.add_column(_TABLE, sa.Column("lease_owner", sa.Text(), nullable=True))
    op.add_column(
        _TABLE,
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Drop the lease owner and expiry columns from agent_runs."""
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_column("lease_expires_at")
        batch.drop_column("lease_owner")
