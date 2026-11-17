"""Persist tenant identity on control-plane aggregates.

Revision ID: 0013
Revises: 0012

Phase: expand
Reversible: yes; the downgrade drops the columns and their indexes
Touches: projects, sources, jobs, activity, providers, workspace_settings, members; existing
         rows get tenant_id DEFAULT
Locks: ACCESS EXCLUSIVE lock on each of the seven tables from its ADD COLUMN until the migration
       run commits, so reads and writes wait through the index builds and any later revision in
       the same run
Deploy: before the application release
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

_TABLES = (
    "projects",
    "sources",
    "jobs",
    "activity",
    "providers",
    "workspace_settings",
    "members",
)


def upgrade() -> None:
    """Add an indexed tenant_id to each control-plane table."""
    for table_name in _TABLES:
        op.add_column(
            table_name,
            sa.Column(
                "tenant_id",
                sa.String(length=128),
                server_default="DEFAULT",
                nullable=False,
            ),
        )
        op.create_index(f"ix_{table_name}_tenant_id", table_name, ["tenant_id"])


def downgrade() -> None:
    """Drop tenant_id and its index from each control-plane table."""
    for table_name in reversed(_TABLES):
        op.drop_index(f"ix_{table_name}_tenant_id", table_name=table_name)
        op.drop_column(table_name, "tenant_id")
