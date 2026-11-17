"""Tighten mcp_api_keys: lowercase-hex key formats, staging keys, spec names.

``key_id`` and ``secret_hash`` were only length-checked. Both now must be
lowercase hex: PostgreSQL checks a regex, SQLite (no ``~`` operator) checks
length plus GLOB. ``environment`` also accepts ``staging``. The constraints are
renamed to ``ck_mcp_key_*``; ``ck_mcp_api_keys_tenant`` is untouched.

Revision ID: 0040
Revises: 0039

Phase: contract; tightens the key format checks and widens the environment check
Reversible: yes; the downgrade fails while a staging key exists
Touches: mcp_api_keys; four check constraints replaced. The upgrade fails while a stored key_id
         or secret_hash is not lowercase hex, so correct or delete such rows first; revoking a
         key keeps its row
Locks: ACCESS EXCLUSIVE lock on mcp_api_keys from the constraint swap until the migration run
       commits; the new check validates every row under it. SQLite copies mcp_api_keys.
Deploy: before the application release
"""

from __future__ import annotations

from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None

_TABLE = "mcp_api_keys"

# The constraints 0036 created, by name.
_OLD = {
    "ck_mcp_api_keys_key_id": "length(key_id) = 24",
    "ck_mcp_api_keys_secret_hash": "length(secret_hash) = 64",
    "ck_mcp_api_keys_environment": "environment IN ('dev', 'prod')",
    "ck_mcp_api_keys_expiry": "expires_at > created_at",
}


def _new_constraints() -> dict[str, str]:
    if op.get_bind().dialect.name == "postgresql":
        key_id = "key_id ~ '^[0-9a-f]{24}$'"
        secret_hash = "secret_hash ~ '^[0-9a-f]{64}$'"
    else:
        key_id = "length(key_id) = 24 AND key_id NOT GLOB '*[^0-9a-f]*'"
        secret_hash = "length(secret_hash) = 64 AND secret_hash NOT GLOB '*[^0-9a-f]*'"
    return {
        "ck_mcp_key_id": key_id,
        "ck_mcp_key_hash": secret_hash,
        "ck_mcp_key_env": "environment IN ('dev', 'staging', 'prod')",
        "ck_mcp_key_expiry": "expires_at > created_at",
    }


def upgrade() -> None:
    """Replace the mcp_api_keys checks with the lowercase-hex and staging-aware ones."""
    # SQLite cannot alter constraints in place; batch mode rebuilds the table
    # (and its index) there, and issues plain ALTER TABLE on PostgreSQL.
    with op.batch_alter_table(_TABLE) as batch:
        for name in _OLD:
            batch.drop_constraint(name, type_="check")
        for name, expression in _new_constraints().items():
            batch.create_check_constraint(name, expression)


def downgrade() -> None:
    """Restore the checks migration 0036 created."""
    # Fails if staging keys exist, which is correct: the 0036 schema cannot
    # hold them.
    with op.batch_alter_table(_TABLE) as batch:
        for name in _new_constraints():
            batch.drop_constraint(name, type_="check")
        for name, expression in _OLD.items():
            batch.create_check_constraint(name, expression)
