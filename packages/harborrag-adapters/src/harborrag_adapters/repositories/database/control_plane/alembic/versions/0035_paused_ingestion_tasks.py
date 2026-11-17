"""Add PAUSED to the public ingestion task lifecycle.

Revision ID: 0035
Revises: 0034

Phase: expand; widens the allowed statuses
Reversible: partly; the downgrade turns PAUSED tasks into RUNNING
Touches: ingestion_tasks; status check constraint replaced
Locks: ACCESS EXCLUSIVE lock on ingestion_tasks from the constraint swap until the migration run
       commits; the new check validates every row under it. SQLite copies ingestion_tasks.
Deploy: before the application release
"""

from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Allow the PAUSED status on ingestion_tasks."""
    with op.batch_alter_table("ingestion_tasks") as batch_op:
        batch_op.drop_constraint("ck_ingestion_task_status", type_="check")
        batch_op.create_check_constraint(
            "ck_ingestion_task_status",
            "status IN ('PENDING','RUNNING','PAUSED','COMPLETED','PARTIAL','FAILED','CANCELLED')",
        )


def downgrade() -> None:
    """Turn PAUSED tasks into RUNNING and restore the earlier status check."""
    # The previous schema has no PAUSED. RUNNING is the state a paused task was
    # paused from and the one resume() restores, so the task carries on there.
    op.execute("UPDATE ingestion_tasks SET status = 'RUNNING' WHERE status = 'PAUSED'")
    with op.batch_alter_table("ingestion_tasks") as batch_op:
        batch_op.drop_constraint("ck_ingestion_task_status", type_="check")
        batch_op.create_check_constraint(
            "ck_ingestion_task_status",
            "status IN ('PENDING','RUNNING','COMPLETED','PARTIAL','FAILED','CANCELLED')",
        )
