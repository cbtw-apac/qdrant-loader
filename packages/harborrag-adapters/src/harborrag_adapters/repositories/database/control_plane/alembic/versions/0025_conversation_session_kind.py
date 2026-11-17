"""Bind each conversation session to the surface that created it.

Chat and agent completions persist turns into the same conversation_memory
table, and a session created through /v1/chat/sessions could be used with
/v1/agent/completions (and vice versa), interleaving both surfaces' turns in
the history recalled for the next prompt. ``kind`` ("chat" | "agent") records
the creating surface so a completion on the other surface is rejected as an
unknown session. Existing rows default to "chat".

Revision ID: 0025
Revises: 0024

Phase: expand
Reversible: yes; the downgrade drops conversation_sessions.kind
Touches: conversation_sessions; existing rows get kind chat
Locks: ACCESS EXCLUSIVE lock on conversation_sessions, taken by the ALTER and held until the
       migration run commits
Deploy: before the application release
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add conversation_sessions.kind, defaulting to chat."""
    op.add_column(
        "conversation_sessions",
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="chat"),
    )


def downgrade() -> None:
    """Drop conversation_sessions.kind."""
    op.drop_column("conversation_sessions", "kind")
