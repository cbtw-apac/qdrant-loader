"""Add user identity, provenance, and bitemporal validity to memories.

``user_id`` becomes the key for USER/SESSION/RUN scopes (``principal_id``
stays the credential that wrote the row); existing rows are backfilled with
``user_id = principal_id``. ``valid_from``/``invalid_at``/``superseded_by``
let a superseded fact stay readable as history, ``source_session_id`` /
``source_message_ids_json`` / ``entity_ids_json`` record where a memory was
extracted from, and ``content_hash`` supports dedupe of restatements.

Revision ID: 0027
Revises: 0026

Phase: expand and data in one revision
Reversible: yes; the downgrade drops the new columns and indexes
Touches: memories; user_id backfilled from principal_id on every row
Locks: ACCESS EXCLUSIVE lock on memories from the ADD COLUMN until the migration run commits,
       covering the UPDATE of every row and both index builds. On SQLite the downgrade copies
       memories.
Deploy: before the application release
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

_TABLE = "memories"
_IX_TENANT_USER = "ix_memories_tenant_user"
_IX_CONTENT_HASH = "ix_memories_content_hash"
_COLUMNS: tuple[sa.Column[Any], ...] = (
    sa.Column("user_id", sa.String(length=512), nullable=True),
    sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
    sa.Column("invalid_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("superseded_by", sa.String(length=128), nullable=True),
    sa.Column("source_session_id", sa.String(length=128), nullable=True),
    sa.Column("source_message_ids_json", sa.Text(), nullable=True),
    sa.Column("entity_ids_json", sa.Text(), nullable=True),
    sa.Column("content_hash", sa.String(length=128), nullable=True),
)


def upgrade() -> None:
    """Add the user, provenance and validity columns to memories and backfill user_id."""
    for column in _COLUMNS:
        op.add_column(_TABLE, column)
    memories = sa.table(_TABLE, sa.column("user_id"), sa.column("principal_id"))
    op.execute(memories.update().values(user_id=memories.c.principal_id))
    op.create_index(_IX_TENANT_USER, _TABLE, ["tenant_id", "user_id"])
    op.create_index(_IX_CONTENT_HASH, _TABLE, ["content_hash"])


def downgrade() -> None:
    """Drop the user, provenance and validity columns and their indexes."""
    op.drop_index(_IX_CONTENT_HASH, table_name=_TABLE)
    op.drop_index(_IX_TENANT_USER, table_name=_TABLE)
    with op.batch_alter_table(_TABLE) as batch:
        for column in reversed(_COLUMNS):
            batch.drop_column(column.name)
