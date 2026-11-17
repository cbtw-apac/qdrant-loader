"""Stop the database from filling in a missing tenant on control-plane rows.

Revision ID: 0048
Revises: 0047

Phase: contract
Reversible: yes; the downgrade puts the ``DEFAULT`` server default back
Touches: projects, sources, secrets, jobs, activity, providers, workspace_settings, members,
         graph_conflicts; stored rows keep their tenant_id
Locks: ACCESS EXCLUSIVE lock on each of the nine tables, taken by the ALTER and held until the
       migration run commits; lock_timeout 5s on Postgres in both directions. SQLite copies each
       table.
Deploy: before the application release
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None

_TABLES = (
    "projects",
    "sources",
    "secrets",
    "jobs",
    "activity",
    "providers",
    "workspace_settings",
    "members",
    "graph_conflicts",
)
_TENANT_ID = sa.String(length=128)
_LEGACY_TENANT = "DEFAULT"


def _bound_lock_wait() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")


def _set_tenant_default(server_default: str | None) -> None:
    for table_name in _TABLES:
        with op.batch_alter_table(table_name) as batch:
            batch.alter_column(
                "tenant_id",
                existing_type=_TENANT_ID,
                existing_nullable=False,
                server_default=server_default,
            )


def upgrade() -> None:
    """Drop the ``DEFAULT`` server default from every ``tenant_id`` column."""
    _bound_lock_wait()
    _set_tenant_default(None)


def downgrade() -> None:
    """Restore the ``DEFAULT`` server default on every ``tenant_id`` column."""
    _bound_lock_wait()
    _set_tenant_default(_LEGACY_TENANT)
