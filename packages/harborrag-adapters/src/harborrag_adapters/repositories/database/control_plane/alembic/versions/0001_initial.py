"""0001: consolidated control-plane and ingestion schema baseline.

Frozen DDL for the first release. Future schema changes must add a new
revision instead of editing this baseline.

Revision ID: 0001
Revises: None

Phase: expand
Reversible: yes; the downgrade drops every baseline table and the rows in them
Touches: every baseline control-plane and ingestion table, created empty
Locks: none on upgrade; the downgrade takes an ACCESS EXCLUSIVE lock on every baseline table to
       drop it, waits for open queries and blocks new ones until it commits
Deploy: before the application release
"""

from __future__ import annotations

from harborrag_adapters.repositories.database.control_plane.alembic.baseline import (
    control_plane,
    ingestion,
)

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the full initial control-plane and ingestion schema."""
    control_plane.create_tables()
    ingestion.create_tables()


def downgrade() -> None:
    """Drop the complete baseline in reverse dependency order."""
    ingestion.drop_tables()
    control_plane.drop_tables()
