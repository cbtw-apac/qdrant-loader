"""Flag a conversation message whose text is only what a stream delivered.

An interrupted stream now persists the text the user already saw instead of
discarding the turn. Without this column that text is indistinguishable from
a finished answer, which is worse than losing it: a later turn would replay a
truncated answer as if the assistant had meant to stop there. Existing rows
predate interrupted-turn persistence, so they are complete by definition and
the server default of false is the correct backfill.

Revision ID: 0030
Revises: 0029

Phase: expand
Reversible: yes; the downgrade drops the partial flag
Touches: conversation_messages; existing rows read as not partial
Locks: ACCESS EXCLUSIVE lock on conversation_messages, taken by the ALTER and held until the
       migration run commits
Deploy: before the application release
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None

_TABLE = "conversation_messages"
_COLUMN = "partial"


def upgrade() -> None:
    """Add the partial flag to conversation_messages, false by default."""
    op.add_column(
        _TABLE,
        sa.Column(_COLUMN, sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    """Drop the partial flag from conversation_messages."""
    op.drop_column(_TABLE, _COLUMN)
