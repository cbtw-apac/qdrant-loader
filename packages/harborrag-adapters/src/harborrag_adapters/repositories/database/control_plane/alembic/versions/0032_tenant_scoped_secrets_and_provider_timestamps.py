"""Tenant-scope stored secrets and timestamp the model-provider rows.

``secrets`` had no tenant column and ``SqlSecretsRepository.resolve`` was a
bare primary-key lookup, so any holder of a ref could decrypt it regardless
of which tenant stored it. ``tenant_id`` arrives here (backfilled to
``DEFAULT`` like every other tenant column in this schema) and becomes part
of every resolve/delete, turning a leaked ref into a dud outside its tenant.
A legacy secret takes the tenant of the ``sources`` (or ``providers``) row that
references it; only a ref no row references, or one several tenants reference,
falls back to ``DEFAULT``. Labelling every secret ``DEFAULT`` left another
tenant's source unable to retire its own secrets, and those secrets resolvable
by ``DEFAULT``.

``providers`` and ``routing_rules`` gain ``updated_at`` so a per-tenant model
catalog can be cache-validated by one cheap aggregate (row count plus latest
``updated_at``) instead of re-reading and re-parsing every row per request.
``providers`` has no prior timestamp at all, so its backfill is "now";
``routing_rules`` backfills from its existing ``created_at``. Every writer of
either table must refresh ``updated_at`` on every mutation, otherwise an
in-place edit is invisible to that aggregate.

Revision ID: 0032
Revises: 0031

Phase: expand, data and contract in one revision
Reversible: yes; the downgrade drops secrets.tenant_id and both updated_at columns
Touches: secrets, providers, routing_rules; every row backfilled, with one UPDATE per uniquely
         owned secret reference, reading sources
Locks: ACCESS EXCLUSIVE lock on secrets, providers and routing_rules, each from its ADD COLUMN
       until the migration run commits, covering the backfills (one UPDATE per uniquely owned
       secret reference), the NOT NULL changes and the secrets index build. SQLite copies each
       table.
Deploy: before the application release
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None

_SECRETS = "secrets"
_PROVIDERS = "providers"
_ROUTING_RULES = "routing_rules"
_TENANT_ID = sa.String(length=128)
_TIMESTAMP = sa.DateTime(timezone=True)
_IX_SECRETS_TENANT = "ix_secrets_tenant_id"


def _owning_tenants() -> dict[str, str]:
    """Map each legacy secret ref to the single tenant whose rows reference it."""
    bind = op.get_bind()
    owners: dict[str, set[str]] = {}
    for tenant_id, refs in bind.execute(sa.text("SELECT tenant_id, secret_refs FROM sources")):
        # JSON comes back decoded on PostgreSQL and as text on SQLite.
        decoded = json.loads(refs) if isinstance(refs, str) else refs
        for ref in decoded or ():
            if isinstance(ref, str):
                owners.setdefault(ref, set()).add(tenant_id)
    for tenant_id, ref in bind.execute(
        sa.text(f"SELECT tenant_id, secret_ref FROM {_PROVIDERS} WHERE secret_ref IS NOT NULL")
    ):
        owners.setdefault(ref, set()).add(tenant_id)
    return {ref: tenants.pop() for ref, tenants in owners.items() if len(tenants) == 1}


def _backfill_secret_tenants() -> None:
    # Unconditional per ref: the server default has already set every existing
    # row to DEFAULT, so a ``WHERE tenant_id IS NULL`` would match nothing.
    secrets = sa.table(_SECRETS, sa.column("ref"), sa.column("tenant_id"))
    for ref, tenant_id in _owning_tenants().items():
        op.execute(secrets.update().where(secrets.c.ref == ref).values(tenant_id=tenant_id))


def _backfill_routing_rules() -> None:
    rules = sa.table(_ROUTING_RULES, sa.column("updated_at"), sa.column("created_at"))
    op.execute(rules.update().values(updated_at=rules.c.created_at))


def upgrade() -> None:
    """Add secrets.tenant_id and the provider and routing-rule timestamps, backfilled."""
    # tenant_id carries a server_default so the column is populated for legacy
    # rows and for any insert that predates the repository change; it still
    # arrives nullable and is tightened through batch_alter_table because
    # SQLite has no ALTER COLUMN.
    op.add_column(
        _SECRETS,
        sa.Column("tenant_id", _TENANT_ID, nullable=True, server_default="DEFAULT"),
    )
    op.execute(sa.text(f"UPDATE {_SECRETS} SET tenant_id = 'DEFAULT' WHERE tenant_id IS NULL"))
    _backfill_secret_tenants()
    with op.batch_alter_table(_SECRETS) as batch:
        batch.alter_column("tenant_id", existing_type=_TENANT_ID, nullable=False)
    op.create_index(_IX_SECRETS_TENANT, _SECRETS, ["tenant_id"])

    # providers has never had a timestamp of any kind, so "now" is the only
    # honest backfill for rows that already exist.
    op.add_column(_PROVIDERS, sa.Column("updated_at", _TIMESTAMP, nullable=True))
    op.execute(sa.text(f"UPDATE {_PROVIDERS} SET updated_at = CURRENT_TIMESTAMP"))
    with op.batch_alter_table(_PROVIDERS) as batch:
        batch.alter_column("updated_at", existing_type=_TIMESTAMP, nullable=False)

    op.add_column(_ROUTING_RULES, sa.Column("updated_at", _TIMESTAMP, nullable=True))
    _backfill_routing_rules()
    with op.batch_alter_table(_ROUTING_RULES) as batch:
        batch.alter_column("updated_at", existing_type=_TIMESTAMP, nullable=False)


def downgrade() -> None:
    """Drop secrets.tenant_id and the provider and routing-rule timestamps."""
    with op.batch_alter_table(_ROUTING_RULES) as batch:
        batch.drop_column("updated_at")
    with op.batch_alter_table(_PROVIDERS) as batch:
        batch.drop_column("updated_at")
    op.drop_index(_IX_SECRETS_TENANT, table_name=_SECRETS)
    with op.batch_alter_table(_SECRETS) as batch:
        batch.drop_column("tenant_id")
