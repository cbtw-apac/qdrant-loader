"""Leader-election leases for singleton background jobs (ML2 multi-process hardening).

A row means: at most one process may run the named background job at a
time. ``try_acquire`` renews it atomically via a conditional UPDATE, so the
row must already exist -- this migration seeds one for the ingestion
progress bridge, already expired, so the first process to tick claims it.

Revision ID: 0017
Revises: 0016

Phase: expand, with one seeded row
Reversible: yes; the downgrade drops singleton_leases
Touches: singleton_leases (new), one seeded row
Locks: none on upgrade; the downgrade takes an ACCESS EXCLUSIVE lock on singleton_leases to drop
       it
Deploy: before the application release
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

_TZDT = sa.DateTime(timezone=True)

_SINGLETON_LEASES = sa.table(
    "singleton_leases",
    sa.column("name", sa.Text()),
    sa.column("holder", sa.Text()),
    sa.column("expires_at", _TZDT),
)


def upgrade() -> None:
    """Create singleton_leases and seed the ingestion progress bridge lease."""
    op.create_table(
        "singleton_leases",
        sa.Column("name", sa.Text(), primary_key=True),
        sa.Column("holder", sa.Text(), nullable=False),
        sa.Column("expires_at", _TZDT, nullable=False),
    )
    op.bulk_insert(
        _SINGLETON_LEASES,
        [
            {
                "name": "ingestion_progress_bridge",
                "holder": "",
                "expires_at": datetime(1970, 1, 1, tzinfo=UTC),
            }
        ],
    )


def downgrade() -> None:
    """Drop singleton_leases."""
    op.drop_table("singleton_leases")
