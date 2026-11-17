"""Remember source links whose targets are not published, for later repair.

Revision ID: 0039
Revises: 0038

Phase: expand
Reversible: yes; the downgrade drops the table and its rows
Touches: unresolved_source_relations (new)
Locks: creating the table takes a SHARE ROW EXCLUSIVE lock on documents for its foreign key, so
       document writes wait until the migration run commits; the downgrade takes an ACCESS
       EXCLUSIVE lock on unresolved_source_relations to drop it
Deploy: before the application release
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None

_TABLE = "unresolved_source_relations"
_INDEX = "ix_unresolved_source_relations_target"


def upgrade() -> None:
    """Create unresolved_source_relations and its target index."""
    op.create_table(
        _TABLE,
        sa.Column(
            "declaring_document_id",
            sa.String(128),
            sa.ForeignKey("documents.document_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("target_source_item_id", sa.String(512), primary_key=True),
        sa.Column("predicate", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("declaring_document_version_id", sa.String(128), nullable=False),
        sa.Column("connector_type", sa.String(32), nullable=False),
        sa.Column("connection_id", sa.String(255), nullable=False),
        sa.Column("target_connector_type", sa.String(32), nullable=False),
        sa.Column("relation_type", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        _INDEX,
        _TABLE,
        ["tenant_id", "target_connector_type", "target_source_item_id"],
    )


def downgrade() -> None:
    """Drop unresolved_source_relations and its target index."""
    op.drop_index(_INDEX, table_name=_TABLE)
    op.drop_table(_TABLE)
