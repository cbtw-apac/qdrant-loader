"""Drop agent-run checkpoints; HarborRAG no longer runs agents.

Revision ID: 0044
Revises: 0043

Phase: contract
Reversible: no, because the downgrade restores an empty agent_runs and the dropped rows are gone
Touches: agent_runs; dropped with every stored checkpoint
Locks: ACCESS EXCLUSIVE lock on agent_runs to drop it, held until the migration run commits; the
       downgrade takes a SHARE ROW EXCLUSIVE lock on conversation_sessions for the restored
       foreign key
Deploy: after the application release

The upgrade deletes every stored checkpoint. The downgrade restores the empty
0043 table shape only; the dropped rows cannot be recovered.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None

_TABLE = "agent_runs"
_IX_SESSION = "ix_agent_runs_session_id"
_IX_STATUS = "ix_agent_runs_status"
_IX_USER_SESSION = "ix_agent_runs_user_session"


def upgrade() -> None:
    """Drop agent_runs and every stored checkpoint."""
    op.drop_table(_TABLE)


def downgrade() -> None:
    """Recreate an empty agent_runs with its indexes."""
    op.create_table(
        _TABLE,
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("principal_id", sa.String(length=512), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("stop_reason", sa.String(length=32), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_id", sa.String(length=512), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["conversation_sessions.session_id"],
            name=op.f("fk_agent_runs_session_id_conversation_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("run_id", name=op.f("pk_agent_runs")),
    )
    op.create_index(_IX_SESSION, _TABLE, ["session_id"])
    op.create_index(_IX_STATUS, _TABLE, ["status"])
    op.create_index(_IX_USER_SESSION, _TABLE, ["tenant_id", "user_id", "session_id"])
