"""Compatibility marker for removal reconciliation.

Revision ID: 0003
Revises: 0002

Phase: expand; a marker with no operations
Reversible: yes; there is nothing to undo
Touches: nothing
Locks: none
Deploy: before the application release
"""

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """The consolidated 0001 baseline already contains this schema."""


def downgrade() -> None:
    """The consolidated 0001 baseline owns removal of this schema."""
