from qdrant_loader.core.state.queries import (
    select_document_state,
    select_ingestion_history,
    select_last_ingestion,
)
from sqlalchemy.dialects import sqlite


def _to_sql(statement) -> str:
    return str(
        statement.compile(
            dialect=sqlite.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_select_ingestion_history_without_project_id():
    stmt = select_ingestion_history(source_type="jira", source="proj-a")
    sql = _to_sql(stmt)

    assert "FROM ingestion_history" in sql
    assert "ingestion_history.source_type = 'jira'" in sql
    assert "ingestion_history.source = 'proj-a'" in sql
    assert "AND ingestion_history.project_id =" not in sql


def test_select_ingestion_history_with_project_id():
    stmt = select_ingestion_history(
        source_type="jira", source="proj-a", project_id="project-1"
    )
    sql = _to_sql(stmt)

    assert "ingestion_history.source_type = 'jira'" in sql
    assert "ingestion_history.source = 'proj-a'" in sql
    assert "ingestion_history.project_id = 'project-1'" in sql


def test_select_last_ingestion_orders_desc_by_last_successful_ingestion():
    stmt = select_last_ingestion(source_type="git", source="repo-1")
    sql = _to_sql(stmt)

    assert "FROM ingestion_history" in sql
    assert "ingestion_history.source_type = 'git'" in sql
    assert "ingestion_history.source = 'repo-1'" in sql
    assert "ORDER BY ingestion_history.last_successful_ingestion DESC" in sql


def test_select_last_ingestion_with_project_id():
    stmt = select_last_ingestion(
        source_type="git", source="repo-1", project_id="project-2"
    )
    sql = _to_sql(stmt)

    assert "ingestion_history.project_id = 'project-2'" in sql
    assert "ORDER BY ingestion_history.last_successful_ingestion DESC" in sql


def test_select_document_state_without_optional_filters():
    stmt = select_document_state(source_type="confluence", source="space-a")
    sql = _to_sql(stmt)

    assert "FROM document_states" in sql
    assert "document_states.source_type = 'confluence'" in sql
    assert "document_states.source = 'space-a'" in sql
    assert "AND document_states.document_id =" not in sql
    assert "AND document_states.project_id =" not in sql


def test_select_document_state_with_document_id_and_project_id():
    stmt = select_document_state(
        source_type="confluence",
        source="space-a",
        document_id="doc-123",
        project_id="project-3",
    )
    sql = _to_sql(stmt)

    assert "document_states.source_type = 'confluence'" in sql
    assert "document_states.source = 'space-a'" in sql
    assert "document_states.document_id = 'doc-123'" in sql
    assert "document_states.project_id = 'project-3'" in sql
