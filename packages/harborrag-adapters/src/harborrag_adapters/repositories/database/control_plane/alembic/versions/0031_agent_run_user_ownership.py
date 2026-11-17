"""Own agent runs by the human, not by the credential that acted.

Migration 0028 made ``conversation_sessions``/``conversation_messages``
user-owned, but ``agent_runs`` -- whose foreign-key parent is that very
sessions table -- kept filtering ``(tenant_id, principal_id, session_id)``.
One service principal fronting several people therefore left ``session_id``
as the only separator, so a known or guessed run id let one human read,
checkpoint steps into, and *resume* another's run, replaying somebody else's
conversation into the model.

``user_id`` becomes part of the key (backfilled from ``principal_id``, which
stays stored purely for audit) and an identity index leading on
``(tenant_id, user_id, session_id)`` replaces the redundant single-column
tenant index. ``run_id`` remains the primary key, so the lookup-by-run path
is unchanged.

Revision ID: 0031
Revises: 0030

Phase: expand, data and contract in one revision
Reversible: yes; the downgrade drops agent_runs.user_id and restores the tenant index
Touches: agent_runs; user_id backfilled from principal_id on every row
Locks: ACCESS EXCLUSIVE lock on agent_runs from the index drop until the migration run commits,
       covering the backfill of every row, the NOT NULL change and the index build. SQLite
       copies agent_runs.
Deploy: before the application release
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None

_TABLE = "agent_runs"
_USER_ID = sa.String(length=512)
_IX_TENANT = "ix_agent_runs_tenant_id"
_IX_USER_SESSION = "ix_agent_runs_user_session"


def _backfill() -> None:
    """Existing runs were scoped by the credential, so it is their owner."""
    runs = sa.table(_TABLE, sa.column("user_id"), sa.column("principal_id"))
    op.execute(runs.update().values(user_id=runs.c.principal_id))


def upgrade() -> None:
    """Add agent_runs.user_id, backfill it and index runs by user and session."""
    # Drop the tenant-only index before the batch rebuild so SQLite's table
    # copy never has to recreate an index while the table is being altered.
    op.drop_index(_IX_TENANT, table_name=_TABLE)
    # The column arrives nullable so existing rows can be backfilled, then is
    # tightened through batch_alter_table -- SQLite has no ALTER COLUMN.
    op.add_column(_TABLE, sa.Column("user_id", _USER_ID, nullable=True))
    _backfill()
    with op.batch_alter_table(_TABLE) as batch:
        batch.alter_column("user_id", existing_type=_USER_ID, nullable=False)
    op.create_index(_IX_USER_SESSION, _TABLE, ["tenant_id", "user_id", "session_id"])


def downgrade() -> None:
    """Drop agent_runs.user_id and restore the tenant index."""
    op.drop_index(_IX_USER_SESSION, table_name=_TABLE)
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_column("user_id")
    op.create_index(_IX_TENANT, _TABLE, ["tenant_id"])
