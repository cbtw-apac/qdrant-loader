"""Own conversations by the human, not by the credential that acted.

``conversation_sessions``/``conversation_messages`` were keyed by
``(tenant_id, principal_id, session_id)``. One service principal fronting
several people therefore left ``session_id`` as the only separator, so a
known or guessed session id replayed somebody else's history. ``user_id``
becomes part of the key on both tables (backfilled from ``principal_id``,
which stays stored purely for audit), and the identity indexes are rebuilt
to lead on ``(tenant_id, user_id, ...)`` with a session-led index kept for
the lookup/cascade path.

``conversation_sessions`` also gains ``title`` (nullable) and ``updated_at``
(backfilled from ``created_at``) so a conversation directory can list and
rename conversations sorted by real activity.

Revision ID: 0028
Revises: 0027

Phase: expand, data and contract in one revision
Reversible: yes; the downgrade drops user_id, title and updated_at with their values
Touches: conversation_sessions, conversation_messages; user_id backfilled on every row
Locks: ACCESS EXCLUSIVE lock on conversation_sessions, then on conversation_messages, each from
       its first ALTER until the migration run commits, covering the backfill of every row, the
       NOT NULL changes and the index builds. SQLite copies both tables.
Deploy: before the application release
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None

_SESSIONS = "conversation_sessions"
_MESSAGES = "conversation_messages"
_USER_ID = sa.String(length=512)
_TIMESTAMP = sa.DateTime(timezone=True)

_IX_SESSIONS_USER = "ix_conversation_sessions_user_updated"
_IX_MESSAGES_IDENTITY = "ix_conversation_messages_identity_seq"
_IX_MESSAGES_USER = "ix_conversation_messages_user_seq"
_IX_MESSAGES_SESSION = "ix_conversation_messages_session_seq"


def _backfill_sessions() -> None:
    sessions = sa.table(
        _SESSIONS,
        sa.column("user_id"),
        sa.column("principal_id"),
        sa.column("updated_at"),
        sa.column("created_at"),
    )
    op.execute(
        sessions.update().values(
            user_id=sessions.c.principal_id,
            updated_at=sessions.c.created_at,
        )
    )


def _backfill_messages() -> None:
    messages = sa.table(_MESSAGES, sa.column("user_id"), sa.column("principal_id"))
    op.execute(messages.update().values(user_id=messages.c.principal_id))


def upgrade() -> None:
    """Add user ownership to conversation sessions and messages and backfill it."""
    # Columns arrive nullable so existing rows can be backfilled, then are
    # tightened through batch_alter_table -- SQLite has no ALTER COLUMN.
    op.add_column(_SESSIONS, sa.Column("user_id", _USER_ID, nullable=True))
    op.add_column(_SESSIONS, sa.Column("title", sa.Text(), nullable=True))
    op.add_column(_SESSIONS, sa.Column("updated_at", _TIMESTAMP, nullable=True))
    _backfill_sessions()
    with op.batch_alter_table(_SESSIONS) as batch:
        batch.alter_column("user_id", existing_type=_USER_ID, nullable=False)
        batch.alter_column("updated_at", existing_type=_TIMESTAMP, nullable=False)
    op.create_index(_IX_SESSIONS_USER, _SESSIONS, ["tenant_id", "user_id", "updated_at"])

    # Drop the principal-led index before the batch rebuild so the table copy
    # never has to recreate an index over the column being altered.
    op.drop_index(_IX_MESSAGES_IDENTITY, table_name=_MESSAGES)
    op.add_column(_MESSAGES, sa.Column("user_id", _USER_ID, nullable=True))
    _backfill_messages()
    with op.batch_alter_table(_MESSAGES) as batch:
        batch.alter_column("user_id", existing_type=_USER_ID, nullable=False)
    op.create_index(
        _IX_MESSAGES_USER,
        _MESSAGES,
        ["tenant_id", "user_id", "session_id", "seq"],
    )
    op.create_index(_IX_MESSAGES_SESSION, _MESSAGES, ["session_id", "seq"])


def downgrade() -> None:
    """Drop user ownership and restore the principal-keyed message index."""
    op.drop_index(_IX_MESSAGES_SESSION, table_name=_MESSAGES)
    op.drop_index(_IX_MESSAGES_USER, table_name=_MESSAGES)
    with op.batch_alter_table(_MESSAGES) as batch:
        batch.drop_column("user_id")
    op.create_index(
        _IX_MESSAGES_IDENTITY,
        _MESSAGES,
        ["tenant_id", "principal_id", "session_id", "seq"],
    )

    op.drop_index(_IX_SESSIONS_USER, table_name=_SESSIONS)
    with op.batch_alter_table(_SESSIONS) as batch:
        batch.drop_column("updated_at")
        batch.drop_column("title")
        batch.drop_column("user_id")
