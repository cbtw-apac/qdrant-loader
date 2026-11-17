"""Index task document results by task and status for the progress poll.

Revision ID: 0037
Revises: 0036

Phase: expand
Reversible: yes; the downgrade drops the index
Touches: task_document_results; index only
Locks: SHARE lock on task_document_results from the index build until the migration run commits;
       writes wait, and reads continue unless an earlier revision in the same run already holds
       an exclusive lock on task_document_results. The downgrade takes an ACCESS EXCLUSIVE lock
       on task_document_results to drop the index, so reads wait too
Deploy: before the application release
"""

from __future__ import annotations

from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None

_INDEX = "ix_task_document_results_task_status"
_TABLE = "task_document_results"


def upgrade() -> None:
    """Create the task and status index on task_document_results."""
    # The progress bridge counts a running task's results per status every few
    # seconds. The primary key covers task_id but not status, so each poll read
    # every row of the task; at hundreds of thousands of documents that is a
    # steady load on the shared database for the whole run.
    op.create_index(_INDEX, _TABLE, ["task_id", "status"])


def downgrade() -> None:
    """Drop the task and status index."""
    op.drop_index(_INDEX, table_name=_TABLE)
