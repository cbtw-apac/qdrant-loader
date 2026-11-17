"""Add PostgreSQL-backed conversation memory.

Revision ID: 0009
Revises: 0008

Phase: expand
Reversible: yes; the downgrade drops both tables and their rows
Touches: conversation_sessions, conversation_memory (new)
Locks: none on upgrade; the downgrade takes an ACCESS EXCLUSIVE lock on both tables to drop them
Deploy: before the application release
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

_INDEX = "ix_conversation_memory_identity_created"


def upgrade() -> None:
    """Create the conversation session and memory tables."""
    op.create_table(
        "conversation_sessions",
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("principal_id", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("session_id", name=op.f("pk_conversation_sessions")),
    )
    op.create_table(
        "conversation_memory",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("principal_id", sa.String(length=512), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("user_content", sa.Text(), nullable=False),
        sa.Column("assistant_content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["conversation_sessions.session_id"],
            name=op.f("fk_conversation_memory_session_id_conversation_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_memory")),
    )
    op.create_index(
        _INDEX,
        "conversation_memory",
        ["tenant_id", "principal_id", "session_id", "created_at", "id"],
    )


def downgrade() -> None:
    """Drop the conversation memory and session tables."""
    op.drop_index(_INDEX, table_name="conversation_memory")
    op.drop_table("conversation_memory")
    op.drop_table("conversation_sessions")
