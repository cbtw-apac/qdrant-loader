"""Seed the singleton lease row for control-plane pending-effect recovery.

0017 seeded a lease for the ingestion progress bridge but not for the
pending-effect recovery drain (AppService.recover_pending_control_plane_effects).
``try_acquire`` returns False for a lease name with no row, so without this
seed row the recovery drain silently never acquires the lease in
production and pending effects (secret retirement, audit logging) never
drain.

Revision ID: 0018
Revises: 0017

Phase: data
Reversible: yes; the downgrade deletes the seeded row
Touches: singleton_leases, one row
Locks: none
Deploy: before the application release
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

_TZDT = sa.DateTime(timezone=True)

_SINGLETON_LEASES = sa.table(
    "singleton_leases",
    sa.column("name", sa.Text()),
    sa.column("holder", sa.Text()),
    sa.column("expires_at", _TZDT),
)

_LEASE_NAME = "control_plane_effect_recovery"


def upgrade() -> None:
    """Seed the lease row for pending-effect recovery."""
    op.bulk_insert(
        _SINGLETON_LEASES,
        [
            {
                "name": _LEASE_NAME,
                "holder": "",
                "expires_at": datetime(1970, 1, 1, tzinfo=UTC),
            }
        ],
    )


def downgrade() -> None:
    """Delete the lease row for pending-effect recovery."""
    op.execute(_SINGLETON_LEASES.delete().where(_SINGLETON_LEASES.c.name == _LEASE_NAME))
