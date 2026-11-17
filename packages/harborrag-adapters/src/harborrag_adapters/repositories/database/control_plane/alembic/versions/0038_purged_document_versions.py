"""Add PURGING and PURGED to the document-version lifecycle for the retention TTL.

Revision ID: 0038
Revises: 0037

Phase: expand; widens the allowed statuses
Reversible: partly; the downgrade turns PURGING and PURGED versions into RETIRED
Touches: document_versions; status check constraint replaced
Locks: ACCESS EXCLUSIVE lock on document_versions from the constraint swap until the migration
       run commits; the new check validates every row under it. SQLite copies document_versions.
Deploy: before the application release
"""

from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None

_STATES = (
    "'PENDING','RAW_CAPTURED','CANONICAL_READY','CHUNKS_READY',"
    "'REPRESENTATIONS_READY','PROJECTIONS_STAGED','VERIFIED',"
    "'ACTIVE','RETIRED','FAILED'"
)


def upgrade() -> None:
    """Allow the PURGING and PURGED statuses on document_versions."""
    with op.batch_alter_table("document_versions") as batch_op:
        batch_op.drop_constraint("ck_document_version_status", type_="check")
        batch_op.create_check_constraint(
            "ck_document_version_status",
            f"status IN ({_STATES},'PURGING','PURGED')",
        )


def downgrade() -> None:
    """Turn purged versions into RETIRED and restore the earlier status check."""
    # A purged row has lost its artifacts; RETIRED is the closest state the
    # previous schema can hold, and its replay restores it to PENDING as well.
    op.execute(
        "UPDATE document_versions SET status = 'RETIRED' WHERE status IN ('PURGING', 'PURGED')"
    )
    with op.batch_alter_table("document_versions") as batch_op:
        batch_op.drop_constraint("ck_document_version_status", type_="check")
        batch_op.create_check_constraint(
            "ck_document_version_status",
            f"status IN ({_STATES})",
        )
