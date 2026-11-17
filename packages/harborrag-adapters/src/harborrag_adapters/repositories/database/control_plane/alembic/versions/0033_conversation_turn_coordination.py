"""Serialize conversation messages and support generated titles and turn leases.

Revision ID: 0033
Revises: 0032

Phase: expand, data and contract in one revision
Reversible: partly; the downgrade drops the columns and the constraint and keeps the renumbered
            seq values
Touches: conversation_sessions (four columns, every row updated); conversation_messages
         (duplicate seq values renumbered, unique constraint added)
Locks: ACCESS EXCLUSIVE lock on conversation_sessions from the first ADD COLUMN until the
       migration run commits, so session reads and writes wait through the session and message
       updates; conversation_messages is then locked exclusively while the unique constraint
       builds. SQLite copies conversation_messages.
Deploy: before the application release
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add title source, sequence and turn-lease columns and make message seq unique."""
    op.add_column("conversation_sessions", sa.Column("title_source", sa.String(16), nullable=True))
    op.add_column(
        "conversation_sessions",
        sa.Column("next_message_seq", sa.BigInteger(), nullable=False, server_default="1"),
    )
    op.add_column(
        "conversation_sessions", sa.Column("turn_lease_token", sa.String(64), nullable=True)
    )
    op.add_column(
        "conversation_sessions",
        sa.Column("turn_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        sa.text("UPDATE conversation_sessions SET title_source = 'manual' WHERE title IS NOT NULL")
    )
    # Historical appends could allocate the same seq in separate workers.
    # Preserve the reader's former tie-break order while assigning unique,
    # contiguous positions before enabling the database constraint.
    op.execute(
        sa.text(
            """WITH duplicates AS (
                SELECT tenant_id, user_id, session_id FROM conversation_messages
                GROUP BY tenant_id, user_id, session_id HAVING COUNT(*) > COUNT(DISTINCT seq)
            ), ranked AS (
                SELECT message_id, ROW_NUMBER() OVER (
                    PARTITION BY tenant_id, user_id, session_id
                    ORDER BY seq, created_at, message_id
                ) AS position FROM conversation_messages
                WHERE EXISTS (
                    SELECT 1 FROM duplicates
                    WHERE duplicates.tenant_id = conversation_messages.tenant_id
                      AND duplicates.user_id = conversation_messages.user_id
                      AND duplicates.session_id = conversation_messages.session_id
                )
            ) UPDATE conversation_messages SET seq = (
                SELECT position FROM ranked
                WHERE ranked.message_id = conversation_messages.message_id
            ) WHERE message_id IN (SELECT message_id FROM ranked)"""
        )
    )
    op.execute(
        sa.text(
            """UPDATE conversation_sessions SET next_message_seq = 1 + COALESCE((
                SELECT MAX(seq) FROM conversation_messages
                WHERE conversation_messages.tenant_id = conversation_sessions.tenant_id
                  AND conversation_messages.user_id = conversation_sessions.user_id
                  AND conversation_messages.session_id = conversation_sessions.session_id
            ), 0)"""
        )
    )
    with op.batch_alter_table("conversation_messages") as batch:
        batch.create_unique_constraint(
            "uq_conversation_messages_owner_seq", ["tenant_id", "user_id", "session_id", "seq"]
        )


def downgrade() -> None:
    """Drop the unique seq constraint and the title, sequence and turn-lease columns."""
    with op.batch_alter_table("conversation_messages") as batch:
        batch.drop_constraint("uq_conversation_messages_owner_seq", type_="unique")
    with op.batch_alter_table("conversation_sessions") as batch:
        batch.drop_column("turn_lease_expires_at")
        batch.drop_column("turn_lease_token")
        batch.drop_column("next_message_seq")
        batch.drop_column("title_source")
