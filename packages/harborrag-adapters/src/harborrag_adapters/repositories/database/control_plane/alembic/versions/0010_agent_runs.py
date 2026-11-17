"""Repair legacy conversation memory and add resumable agent-run checkpoints.

Revision ID: 0010
Revises: 0009

Phase: expand, with a data repair on legacy databases
Reversible: partly; the downgrade drops agent_runs and keeps the conversation repair
Touches: agent_runs (new); conversation_sessions and conversation_memory on legacy databases
         only
Locks: creating agent_runs takes a SHARE ROW EXCLUSIVE lock on conversation_sessions for its
       foreign key, so session writes wait until the migration run commits; a legacy database
       also rebuilds conversation_memory under an exclusive lock
Deploy: before the application release

Some development databases were stamped at revision 0009 by an earlier
conversation-memory migration.  That schema had a required ``user_id``
column and did not create ``conversation_sessions`` or its foreign key.  The
revision identifier was subsequently reused, so Alembic cannot distinguish
those databases from ones created by the current 0009 migration.  Repair the
legacy shape here before creating ``agent_runs``, which references the
sessions table.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

_JSON = sa.JSON()
_IX_TENANT = "ix_agent_runs_tenant_id"
_IX_SESSION = "ix_agent_runs_session_id"
_IX_STATUS = "ix_agent_runs_status"
_CONVERSATION_INDEX = "ix_conversation_memory_identity_created"
_CONVERSATION_INDEX_COLUMNS = (
    "tenant_id",
    "principal_id",
    "session_id",
    "created_at",
    "id",
)
_CONVERSATION_FK = "fk_conversation_memory_session_id_conversation_sessions"


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _named_columns(items: Sequence[Mapping[str, Any]], name: str) -> tuple[str, ...] | None:
    for item in items:
        if item.get("name") == name:
            return tuple(item.get("column_names") or ())
    return None


def _create_conversation_sessions() -> None:
    op.create_table(
        "conversation_sessions",
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("principal_id", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("session_id", name=op.f("pk_conversation_sessions")),
    )


def _backfill_conversation_sessions() -> None:
    connection = op.get_bind()
    ambiguous_sessions = connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM ("
            "SELECT session_id FROM conversation_memory GROUP BY session_id "
            "HAVING COUNT(DISTINCT tenant_id) > 1 "
            "OR COUNT(DISTINCT principal_id) > 1"
            ") AS ambiguous_conversation_sessions"
        )
    ).scalar_one()
    if ambiguous_sessions:
        raise RuntimeError(
            "cannot repair legacy conversation memory: one or more session IDs "
            "belong to multiple tenant/principal identities"
        )

    op.execute(
        sa.text(
            "INSERT INTO conversation_sessions "
            "(session_id, tenant_id, principal_id, created_at) "
            "SELECT memory.session_id, MIN(memory.tenant_id), "
            "MIN(memory.principal_id), MIN(memory.created_at) "
            "FROM conversation_memory AS memory "
            "WHERE NOT EXISTS ("
            "SELECT 1 FROM conversation_sessions AS sessions "
            "WHERE sessions.session_id = memory.session_id"
            ") GROUP BY memory.session_id"
        )
    )


def _has_conversation_session_fk() -> bool:
    for foreign_key in _inspector().get_foreign_keys("conversation_memory"):
        if (
            tuple(foreign_key.get("constrained_columns") or ()) == ("session_id",)
            and foreign_key.get("referred_table") == "conversation_sessions"
            and tuple(foreign_key.get("referred_columns") or ()) == ("session_id",)
        ):
            return True
    return False


def _align_conversation_memory_schema(
    columns: set[str],
    *,
    has_session_fk: bool,
) -> None:
    existing_index = _named_columns(
        _inspector().get_indexes("conversation_memory"),
        _CONVERSATION_INDEX,
    )
    if existing_index is not None and existing_index != _CONVERSATION_INDEX_COLUMNS:
        op.drop_index(_CONVERSATION_INDEX, table_name="conversation_memory")

    if "user_id" in columns or not has_session_fk:
        dialect = op.get_bind().dialect.name
        if dialect == "sqlite":
            # SQLite cannot add a foreign key with ALTER TABLE, so rebuild its
            # legacy table while preserving the conversation rows.
            with op.batch_alter_table("conversation_memory", recreate="always") as batch_op:
                if "user_id" in columns:
                    batch_op.drop_column("user_id")
                if not has_session_fk:
                    batch_op.create_foreign_key(
                        _CONVERSATION_FK,
                        "conversation_sessions",
                        ["session_id"],
                        ["session_id"],
                        ondelete="CASCADE",
                    )
        elif dialect == "postgresql":
            if "user_id" in columns:
                op.drop_column("conversation_memory", "user_id")
            if not has_session_fk:
                op.create_foreign_key(
                    _CONVERSATION_FK,
                    "conversation_memory",
                    "conversation_sessions",
                    ["session_id"],
                    ["session_id"],
                    ondelete="CASCADE",
                )
        else:
            raise RuntimeError(f"unsupported migration dialect: {dialect}")


def _ensure_conversation_memory_index() -> None:
    current_index = _named_columns(
        _inspector().get_indexes("conversation_memory"),
        _CONVERSATION_INDEX,
    )
    if current_index is None:
        op.create_index(
            _CONVERSATION_INDEX,
            "conversation_memory",
            list(_CONVERSATION_INDEX_COLUMNS),
        )


def _repair_legacy_conversation_memory() -> None:
    tables = set(_inspector().get_table_names())
    if "conversation_sessions" not in tables:
        _create_conversation_sessions()
    if "conversation_memory" not in tables:
        # Revision 0009 is expected to own this table. Refuse to synthesize an
        # unknown schema silently; this indicates corruption beyond the known
        # legacy revision collision.
        raise RuntimeError("cannot repair revision 0009: conversation_memory table is missing")

    _backfill_conversation_sessions()
    columns = {column["name"] for column in _inspector().get_columns("conversation_memory")}
    _align_conversation_memory_schema(
        columns,
        has_session_fk=_has_conversation_session_fk(),
    )
    _ensure_conversation_memory_index()


def upgrade() -> None:
    """Repair a legacy conversation-memory schema, then create agent_runs."""
    _repair_legacy_conversation_memory()
    op.create_table(
        "agent_runs",
        sa.Column("run_id", sa.String(length=128), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("principal_id", sa.String(length=512), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("stop_reason", sa.String(length=32), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("state_json", _JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["conversation_sessions.session_id"],
            name=op.f("fk_agent_runs_session_id_conversation_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("run_id", name=op.f("pk_agent_runs")),
    )
    op.create_index(_IX_TENANT, "agent_runs", ["tenant_id"])
    op.create_index(_IX_SESSION, "agent_runs", ["session_id"])
    op.create_index(_IX_STATUS, "agent_runs", ["status"])


def downgrade() -> None:
    """Drop agent checkpoints while retaining the data-safe 0009 repair."""
    op.drop_index(_IX_STATUS, table_name="agent_runs")
    op.drop_index(_IX_SESSION, table_name="agent_runs")
    op.drop_index(_IX_TENANT, table_name="agent_runs")
    op.drop_table("agent_runs")
