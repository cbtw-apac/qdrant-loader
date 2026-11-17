"""Allocate job-event sequence numbers atomically.

Revision ID: 0012
Revises: 0011

Phase: expand and data in one revision
Reversible: yes; the downgrade drops jobs.event_sequence
Touches: jobs; event_sequence set on every row from job_events
Locks: ACCESS EXCLUSIVE lock on jobs from the ADD COLUMN until the migration run commits, so
       reads and writes of jobs wait for the whole backfill
Deploy: before the application release
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add jobs.event_sequence and set it from each job's stored events."""
    op.add_column(
        "jobs",
        sa.Column("event_sequence", sa.Integer(), server_default="0", nullable=False),
    )
    op.execute(
        sa.text(
            "UPDATE jobs SET event_sequence = COALESCE(("
            "SELECT MAX(job_events.seq) FROM job_events "
            "WHERE job_events.job_id = jobs.id), 0)"
        )
    )


def downgrade() -> None:
    """Drop jobs.event_sequence."""
    op.drop_column("jobs", "event_sequence")
