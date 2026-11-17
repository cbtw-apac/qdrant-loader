"""Make tenant ownership authoritative.

Revision ID: 0008
Revises: 0007

Phase: expand, data and contract in one revision
Reversible: partly; the downgrade restores the old uniqueness rules and keeps tenant_id. It
            fails while two tenants share a non-null idempotency key or a document identity, so
            resolve those collisions first
Touches: source_scopes, documents, ingestion_tasks; tenant_id backfilled on every row
Locks: the backfill updates every row of the three tables on any database, so conflicting
       updates and deletes wait on those row locks until the migration run commits. A legacy
       database also takes an ACCESS EXCLUSIVE lock on each table from its first ALTER, covering
       the NOT NULL change and the index and constraint rebuilds. SQLite copies each table.
Deploy: before the application release

This migration is intentionally schema-aware. New databases receive these
columns from the consolidated 0001 baseline, while legacy databases stamped
at 0007 still need the forward migration.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

_TENANT_TABLES = ("source_scopes", "documents", "ingestion_tasks")
_TENANT_TYPE = sa.String(128)


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _columns(table_name: str) -> dict[str, Mapping[str, Any]]:
    return {column["name"]: column for column in _inspector().get_columns(table_name)}


def _named_columns(items: Sequence[Mapping[str, Any]], name: str) -> tuple[str, ...] | None:
    for item in items:
        if item.get("name") == name:
            return tuple(item.get("column_names") or ())
    return None


def _index_columns(table_name: str, name: str) -> tuple[str, ...] | None:
    return _named_columns(_inspector().get_indexes(table_name), name)


def _constraint_columns(table_name: str, name: str) -> tuple[str, ...] | None:
    return _named_columns(_inspector().get_unique_constraints(table_name), name)


def _add_missing_tenant_columns() -> None:
    for table_name in _TENANT_TABLES:
        if "tenant_id" not in _columns(table_name):
            op.add_column(
                table_name,
                sa.Column("tenant_id", _TENANT_TYPE, nullable=True),
            )


def _backfill_tenants() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        request_tenant = "request ->> 'tenant_id'"
    elif dialect == "sqlite":
        request_tenant = "json_extract(request, '$.tenant_id')"
    else:
        raise RuntimeError(f"unsupported migration dialect: {dialect}")

    op.execute(
        sa.text(
            "UPDATE ingestion_tasks "
            f"SET tenant_id = COALESCE(tenant_id, {request_tenant}, 'DEFAULT')"
        )
    )
    op.execute(
        sa.text(
            "UPDATE source_scopes SET tenant_id = COALESCE(tenant_id, ("
            "SELECT ingestion_tasks.tenant_id FROM ingestion_tasks "
            "WHERE ingestion_tasks.source_scope_id = source_scopes.source_scope_id "
            "LIMIT 1), 'DEFAULT')"
        )
    )
    op.execute(
        sa.text(
            "UPDATE documents SET tenant_id = COALESCE(tenant_id, ("
            "SELECT source_scopes.tenant_id FROM source_scopes "
            "WHERE source_scopes.source_scope_id = documents.source_scope_id"
            "), 'DEFAULT')"
        )
    )


def _make_tenant_columns_required() -> None:
    for table_name in _TENANT_TABLES:
        tenant = _columns(table_name)["tenant_id"]
        if tenant.get("nullable", True):
            with op.batch_alter_table(table_name) as batch_op:
                batch_op.alter_column(
                    "tenant_id",
                    existing_type=_TENANT_TYPE,
                    nullable=False,
                )


def _ensure_tenant_indexes() -> None:
    for table_name in _TENANT_TABLES:
        index_name = f"ix_{table_name}_tenant_id"
        if _index_columns(table_name, index_name) is None:
            op.create_index(index_name, table_name, ["tenant_id"])


def _ensure_document_identity() -> None:
    name = "uq_document_source_identity"
    expected = ("tenant_id", "connector_type", "connection_id", "source_item_id")
    existing = _constraint_columns("documents", name)
    if existing == expected:
        return
    with op.batch_alter_table("documents") as batch_op:
        if existing is not None:
            batch_op.drop_constraint(name, type_="unique")
        batch_op.create_unique_constraint(name, list(expected))


def _ensure_idempotency_identity() -> None:
    name = "uq_ingestion_task_idempotency_key"
    expected = ("tenant_id", "idempotency_key")
    existing = _index_columns("ingestion_tasks", name)
    if existing == expected:
        return
    if existing is not None:
        op.drop_index(name, table_name="ingestion_tasks")
    op.create_index(
        name,
        "ingestion_tasks",
        list(expected),
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
    )


def upgrade() -> None:
    """Add and backfill authoritative tenant ownership on legacy schemas."""
    _add_missing_tenant_columns()
    _backfill_tenants()
    _make_tenant_columns_required()
    _ensure_tenant_indexes()
    _ensure_document_identity()
    _ensure_idempotency_identity()


def _drop_index_if_present(table_name: str, name: str) -> None:
    if _index_columns(table_name, name) is not None:
        op.drop_index(name, table_name=table_name)


def downgrade() -> None:
    """Restore the pre-tenancy uniqueness rules.

    Intentionally does *not* drop the ``tenant_id`` columns/indexes. Whether
    this revision's ``upgrade()`` added them or they already existed from the
    consolidated 0001 baseline is indistinguishable from schema state alone
    (see the module docstring), so unconditionally dropping them would strip
    tenant scoping from a freshly bootstrapped database that never lacked it
    -- breaking every tenant-filtered query and losing the tenant assignment
    data with no way to recover it short of a restore. Leaving the columns in
    place is always safe: application code built against revision 0007 never
    references ``tenant_id``, so an extra column/index is inert, whereas a
    legacy database that this revision's ``upgrade()`` actually populated
    keeps its tenant data intact across a rollback.
    """
    idempotency_name = "uq_ingestion_task_idempotency_key"
    _drop_index_if_present("ingestion_tasks", idempotency_name)
    op.create_index(
        idempotency_name,
        "ingestion_tasks",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
    )

    document_name = "uq_document_source_identity"
    existing = _constraint_columns("documents", document_name)
    with op.batch_alter_table("documents") as batch_op:
        if existing is not None:
            batch_op.drop_constraint(document_name, type_="unique")
        batch_op.create_unique_constraint(
            document_name,
            ["connector_type", "connection_id", "source_item_id"],
        )
