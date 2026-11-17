"""Persist conversation history per message; retire the paired-turn table.

``conversation_memory`` stored one row per completed user/assistant pair, so
tool calls, citations, token counts, and the run that produced an answer had
nowhere to live. ``conversation_messages`` stores every message with those
attributes and a per-session ``seq`` ordering key. Existing pairs are copied
across as two messages each (``legacy-<id>-user`` / ``legacy-<id>-assistant``,
``seq`` ``2*id`` / ``2*id+1``) and the old table is renamed to
``conversation_memory_legacy``, kept read-only for one release.

Downgrade renames the legacy table back and re-pairs the user/assistant
messages appended since the upgrade into it, then drops the message table.

Revision ID: 0026
Revises: 0025

Phase: expand and data in one revision
Reversible: partly; the downgrade keeps only a user message directly answered by an assistant
            message. Unanswered or repeated user messages, messages of other roles and the
            attributes a pair cannot hold are lost
Touches: conversation_messages (new, filled from every stored pair); conversation_memory renamed
         conversation_memory_legacy
Locks: creating conversation_messages takes a SHARE ROW EXCLUSIVE lock on conversation_sessions
       for its foreign key, so session writes wait through the copy of every stored pair; the
       rename then takes an ACCESS EXCLUSIVE lock on conversation_memory. Both are held until
       the migration run commits. The copy reads conversation_memory once and does not lock it
Deploy: before the application release, with every writer to conversation_memory stopped. A pair
        written during the copy stays only in conversation_memory_legacy and is missing from
        conversation_messages
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

_TABLE = "conversation_messages"
_LEGACY = "conversation_memory"
_LEGACY_RENAMED = "conversation_memory_legacy"
_INDEX = "ix_conversation_messages_identity_seq"
_LEGACY_PREFIX = "legacy-"

_MESSAGES = sa.table(
    _TABLE,
    sa.column("message_id", sa.String(128)),
    sa.column("tenant_id", sa.String(128)),
    sa.column("principal_id", sa.String(512)),
    sa.column("session_id", sa.String(128)),
    sa.column("role", sa.String(16)),
    sa.column("content", sa.Text()),
    sa.column("token_count", sa.Integer()),
    sa.column("tool_calls_json", sa.Text()),
    sa.column("tool_call_id", sa.String(128)),
    sa.column("citations_json", sa.Text()),
    sa.column("run_id", sa.String(128)),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("seq", sa.BigInteger()),
)


def _legacy_table(name: str) -> sa.TableClause:
    return sa.table(
        name,
        sa.column("id", sa.Integer()),
        sa.column("tenant_id", sa.String(128)),
        sa.column("principal_id", sa.String(512)),
        sa.column("session_id", sa.String(128)),
        sa.column("user_content", sa.Text()),
        sa.column("assistant_content", sa.Text()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )


def _aware(value: datetime) -> datetime:
    """SQLite hands back naive timestamps; the rows were always written as UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _messages_from_pair(row: sa.Row[Any]) -> Iterator[dict[str, Any]]:
    base = {
        "tenant_id": row.tenant_id,
        "principal_id": row.principal_id,
        "session_id": row.session_id,
        "token_count": None,
        "tool_calls_json": None,
        "tool_call_id": None,
        "citations_json": None,
        "run_id": None,
        "created_at": _aware(row.created_at),
    }
    yield {
        **base,
        "message_id": f"{_LEGACY_PREFIX}{row.id}-user",
        "role": "user",
        "content": row.user_content,
        "seq": row.id * 2,
    }
    yield {
        **base,
        "message_id": f"{_LEGACY_PREFIX}{row.id}-assistant",
        "role": "assistant",
        "content": row.assistant_content,
        "seq": row.id * 2 + 1,
    }


def _backfill_messages() -> None:
    legacy = _legacy_table(_LEGACY)
    rows = op.get_bind().execute(sa.select(legacy).order_by(legacy.c.id)).all()
    messages = [message for row in rows for message in _messages_from_pair(row)]
    if messages:
        op.bulk_insert(_MESSAGES, messages)


def _pairs_from_messages(rows: Sequence[sa.Row[Any]]) -> list[dict[str, Any]]:
    """Re-pair post-upgrade user/assistant messages (oldest-first per session)."""
    pairs: list[dict[str, Any]] = []
    pending: dict[tuple[str, str, str], sa.Row[Any]] = {}
    for row in rows:
        key = (row.tenant_id, row.principal_id, row.session_id)
        if row.role == "user":
            pending[key] = row
        elif row.role == "assistant" and key in pending:
            user = pending.pop(key)
            pairs.append(
                {
                    "tenant_id": row.tenant_id,
                    "principal_id": row.principal_id,
                    "session_id": row.session_id,
                    "user_content": user.content,
                    "assistant_content": row.content,
                    "created_at": _aware(row.created_at),
                }
            )
    return pairs


def _restore_pairs() -> None:
    statement = (
        sa.select(_MESSAGES)
        .where(_MESSAGES.c.message_id.notlike(f"{_LEGACY_PREFIX}%"))
        .order_by(
            _MESSAGES.c.tenant_id,
            _MESSAGES.c.principal_id,
            _MESSAGES.c.session_id,
            _MESSAGES.c.seq,
            _MESSAGES.c.created_at,
        )
    )
    pairs = _pairs_from_messages(op.get_bind().execute(statement).all())
    if pairs:
        op.bulk_insert(_legacy_table(_LEGACY), pairs)


def upgrade() -> None:
    """Create conversation_messages, copy the stored pairs and retire the old table."""
    op.create_table(
        _TABLE,
        sa.Column("message_id", sa.String(length=128), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("principal_id", sa.String(length=512), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("tool_calls_json", sa.Text(), nullable=True),
        sa.Column("tool_call_id", sa.String(length=128), nullable=True),
        sa.Column("citations_json", sa.Text(), nullable=True),
        sa.Column("run_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["conversation_sessions.session_id"],
            name=op.f("fk_conversation_messages_session_id_conversation_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("message_id", name=op.f("pk_conversation_messages")),
    )
    op.create_index(_INDEX, _TABLE, ["tenant_id", "principal_id", "session_id", "seq"])
    _backfill_messages()
    # Indexes and constraints keep their pre-rename names on both dialects;
    # ConversationMemoryLegacyRow declares those same names.
    op.rename_table(_LEGACY, _LEGACY_RENAMED)


def downgrade() -> None:
    """Restore conversation_memory from the messages and drop conversation_messages."""
    op.rename_table(_LEGACY_RENAMED, _LEGACY)
    _restore_pairs()
    op.drop_index(_INDEX, table_name=_TABLE)
    op.drop_table(_TABLE)
