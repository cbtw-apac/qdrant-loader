"""Add the durable model-usage accounting table.

Token and cost footprints were only ever visible in logs, so nothing could
answer "what has this human spent this month". ``model_usage`` records one
row per model call, attributed to ``(tenant_id, user_id)`` with
``principal_id`` kept for audit, indexed for the tenant/user/window
aggregations the port exposes.

Revision ID: 0029
Revises: 0028

Phase: expand
Reversible: yes; the downgrade drops model_usage and its rows
Touches: model_usage (new)
Locks: none on upgrade; the downgrade takes an ACCESS EXCLUSIVE lock on model_usage to drop it
Deploy: before the application release
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None

_TABLE = "model_usage"
_IX_TENANT = "ix_model_usage_tenant_id"
_IX_USER = "ix_model_usage_user_id"
_IX_CREATED = "ix_model_usage_created_at"


def upgrade() -> None:
    """Create model_usage and its indexes."""
    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.String(length=512), nullable=False),
        sa.Column("principal_id", sa.String(length=512), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=True),
        sa.Column("run_id", sa.String(length=128), nullable=True),
        sa.Column("surface", sa.String(length=16), nullable=False),
        sa.Column("logical_model", sa.String(length=256), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("provider_model", sa.String(length=256), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=True),
        sa.Column("finish_reason", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_usage")),
    )
    op.create_index(_IX_TENANT, _TABLE, ["tenant_id"])
    op.create_index(_IX_USER, _TABLE, ["user_id"])
    op.create_index(_IX_CREATED, _TABLE, ["created_at"])


def downgrade() -> None:
    """Drop model_usage and its indexes."""
    op.drop_index(_IX_CREATED, table_name=_TABLE)
    op.drop_index(_IX_USER, table_name=_TABLE)
    op.drop_index(_IX_TENANT, table_name=_TABLE)
    op.drop_table(_TABLE)
