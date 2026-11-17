"""Add an ordered event log for ingestion tasks (WS/SSE reconnect replay).

Mirrors job_events/jobs.event_sequence (see 0012_atomic_job_event_sequence.py):
an atomically-claimed per-task sequence counter plus an append-only log table.

Revision ID: 0015
Revises: 0014

Phase: expand
Reversible: yes; the downgrade drops task_events and ingestion_tasks.event_sequence
Touches: ingestion_tasks (event_sequence, 0 on existing rows), task_events (new)
Locks: ACCESS EXCLUSIVE lock on ingestion_tasks, taken by the ALTER and held until the migration
       run commits
Deploy: before the application release
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

_JSON = sa.JSON()
_TZDT = sa.DateTime(timezone=True)


def upgrade() -> None:
    """Add ingestion_tasks.event_sequence and create task_events."""
    op.add_column(
        "ingestion_tasks",
        sa.Column("event_sequence", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_table(
        "task_events",
        sa.Column(
            "task_id",
            sa.String(128),
            sa.ForeignKey("ingestion_tasks.task_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("seq", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("trace_id", sa.Text(), nullable=False),
        sa.Column("payload_json", _JSON, nullable=False),
        sa.Column("created_at", _TZDT, nullable=False),
    )


def downgrade() -> None:
    """Drop task_events and ingestion_tasks.event_sequence."""
    op.drop_table("task_events")
    op.drop_column("ingestion_tasks", "event_sequence")
