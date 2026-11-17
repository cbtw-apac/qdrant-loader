"""Hashed, tenant-bound MCP reader keys issued by the CLI.

Revision ID: 0036
Revises: 0035

Phase: expand
Reversible: yes; the downgrade drops mcp_api_keys and every stored key
Touches: mcp_api_keys (new)
Locks: none on upgrade; the downgrade takes an ACCESS EXCLUSIVE lock on mcp_api_keys to drop it
Deploy: before the application release
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create mcp_api_keys and its tenant and owner index."""
    op.create_table(
        "mcp_api_keys",
        sa.Column("key_id", sa.String(24), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("owner", sa.String(128), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("secret_hash", sa.String(64), nullable=False),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.Text(), nullable=True),
        sa.Column("revocation_reason", sa.Text(), nullable=True),
        sa.CheckConstraint("length(key_id) = 24", name="ck_mcp_api_keys_key_id"),
        sa.CheckConstraint("length(secret_hash) = 64", name="ck_mcp_api_keys_secret_hash"),
        sa.CheckConstraint("environment IN ('dev', 'prod')", name="ck_mcp_api_keys_environment"),
        sa.CheckConstraint("expires_at > created_at", name="ck_mcp_api_keys_expiry"),
        sa.CheckConstraint("tenant_id <> '*'", name="ck_mcp_api_keys_tenant"),
    )
    op.create_index("ix_mcp_api_keys_tenant_owner", "mcp_api_keys", ["tenant_id", "owner"])


def downgrade() -> None:
    """Drop mcp_api_keys."""
    op.drop_table("mcp_api_keys")
