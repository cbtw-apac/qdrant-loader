"""Compatibility marker for overlapping source scopes.

Revision ID: 0004
Revises: 0003

Phase: expand; a marker with no operations
Reversible: yes; there is nothing to undo
Touches: nothing
Locks: none
Deploy: before the application release
"""

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """The consolidated 0001 baseline already contains this schema."""


def downgrade() -> None:
    """The consolidated 0001 baseline owns removal of this schema."""
