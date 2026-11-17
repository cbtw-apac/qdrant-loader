"""Add projects.version for conditional writes (ETag and If-Match).

Revision ID: 0043
Revises: 0042

Phase: expand
Reversible: yes; the downgrade drops projects.version
Touches: projects; existing rows get version 1
Locks: ACCESS EXCLUSIVE lock on projects, taken by the ALTER and held until the migration run
       commits. SQLite copies projects.
Deploy: before the application release
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add projects.version, starting at 1."""
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("version", sa.Integer(), server_default="1", nullable=False))


def downgrade() -> None:
    """Drop projects.version."""
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("version")
