"""Store encrypted secret values alongside their refs.

Revision ID: 0014
Revises: 0013

Phase: expand
Reversible: yes; the downgrade drops secrets.ciphertext and the values stored in it
Touches: secrets; nullable column, no backfill
Locks: ACCESS EXCLUSIVE lock on secrets, taken by the ALTER and held until the migration run
       commits
Deploy: before the application release
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the nullable secrets.ciphertext column."""
    # Nullable: no prior row ever had a value to backfill -- the "secrets"
    # table existed with refs/provenance only, no backend that could persist
    # one. SqlSecretsRepository.put() always sets this on insert.
    op.add_column(
        "secrets",
        sa.Column("ciphertext", sa.LargeBinary(), nullable=True),
    )


def downgrade() -> None:
    """Drop secrets.ciphertext."""
    op.drop_column("secrets", "ciphertext")
