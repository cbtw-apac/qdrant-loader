"""Unit tests for Jira connector JQL/timestamp/hostname utility helpers."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from jira_test_helpers import FakeJiraClient, cloud_config

from harborrag_adapters.connectors.jira import JiraConnector
from harborrag_adapters.connectors.jira.query import (
    build_jql,
    format_query_timestamp,
    is_cloud_hostname,
    narrow_jql,
    search_body,
)
from harborrag_adapters.connectors.schemas import ConnectorQuery

pytestmark = [pytest.mark.unit, pytest.mark.whitebox]


def test_build_jql_supports_incremental_sync_and_rejects_bad_project_key() -> None:
    jql = build_jql(
        project_keys=["ENG"],
        issue_types=["Task"],
        statuses=["In Progress"],
        labels=["rag"],
        updated_after=datetime(2024, 1, 2, 3, 4, tzinfo=UTC),
    )

    assert 'project in ("ENG")' in jql
    assert 'issuetype in ("Task")' in jql
    assert 'status in ("In Progress")' in jql
    assert 'labels in ("rag")' in jql
    assert 'updated >= "2024/01/02 03:04"' in jql
    assert "order by updated ASC, key ASC" in jql
    with pytest.raises(ValueError, match="Invalid JIRA project key"):
        build_jql(project_keys=['ENG" OR project = "OPS'])


def test_jql_from_query_wraps_raw_jql_in_the_project_boundary() -> None:
    connector = JiraConnector(cloud_config(), client=FakeJiraClient())

    jql = connector._jql_from_query(
        ConnectorQuery(
            filters={
                "project_keys": "ENG",
                "issue_types": ["Bug", "Task"],
                "jql": "key = ENG-5",
            }
        )
    )

    assert jql == ('project in ("ENG") and (key = ENG-5) order by updated ASC, key ASC')


@pytest.mark.parametrize(
    "query",
    [
        pytest.param(ConnectorQuery(filters={"project_keys": ["ENG", "OPS"]}), id="project-keys"),
        pytest.param(ConnectorQuery(filters={"project_key": "OPS"}), id="project-key"),
        pytest.param(ConnectorQuery(path="OPS"), id="path"),
    ],
)
def test_jql_from_query_with_projects_outside_the_configured_ones_raises(
    query: ConnectorQuery,
) -> None:
    connector = JiraConnector(cloud_config(), client=FakeJiraClient())

    with pytest.raises(ValueError, match="configured connection projects"):
        connector._jql_from_query(query)


def test_jql_from_query_without_configured_projects_accepts_any_project() -> None:
    connector = JiraConnector(cloud_config(project_keys=[]), client=FakeJiraClient())

    jql = connector._jql_from_query(ConnectorQuery(filters={"project_keys": ["OPS"]}))

    assert jql.startswith('project in ("OPS")')


def test_narrow_jql_ands_the_run_condition_onto_the_connection_condition() -> None:
    assert narrow_jql("project = CPM", "status = Done") == "(project = CPM) and (status = Done)"


@pytest.mark.parametrize(
    ("connection_jql", "run_jql", "expected"),
    [
        pytest.param(
            "project = CPM ORDER BY created",
            "status = Done",
            "(project = CPM) and (status = Done) ORDER BY created",
            id="connection-ordering",
        ),
        pytest.param(
            "project = CPM ORDER BY created",
            "status = Done order by key",
            "(project = CPM) and (status = Done) order by key",
            id="run-ordering-wins",
        ),
    ],
)
def test_narrow_jql_keeps_the_run_ordering_else_the_connection_ordering(
    connection_jql: str, run_jql: str, expected: str
) -> None:
    assert narrow_jql(connection_jql, run_jql) == expected


@pytest.mark.parametrize(
    ("connection_jql", "run_jql"),
    [
        pytest.param("project = CPM", "x = 1) or (project = HR", id="run-closes-its-group"),
        pytest.param("project = CPM) or (project = HR", "x = 1", id="connection-closes-its-group"),
    ],
)
def test_narrow_jql_with_either_side_reaching_outside_its_group_raises(
    connection_jql: str, run_jql: str
) -> None:
    with pytest.raises(ValueError, match="Raw query"):
        narrow_jql(connection_jql, run_jql)


def test_format_query_timestamp_assumes_utc_for_naive_datetime() -> None:
    naive = datetime(2024, 1, 2, 3, 4)
    assert format_query_timestamp(naive) == "2024/01/02 03:04"


def test_is_cloud_hostname_with_unparseable_url_returns_false() -> None:
    assert is_cloud_hostname("http://[::1") is False


def test_build_jql_with_raw_jql_and_no_project_returns_it_verbatim() -> None:
    assert build_jql(raw_jql="key = ENG-9") == "key = ENG-9"


def test_build_jql_preserves_raw_ordering_inside_project_boundary() -> None:
    assert build_jql(
        project_keys=["ENG"],
        raw_jql="statusCategory != Done ORDER BY priority DESC",
    ) == ('project in ("ENG") and (statusCategory != Done) ORDER BY priority DESC')


@pytest.mark.parametrize(
    "raw_jql",
    [
        pytest.param('key = ENG-1) or (project = "OPS"', id="closes-the-wrapping-group"),
        pytest.param(
            "key = ENG-1) or (project = OPS ORDER BY created", id="closes-the-group-before-order-by"
        ),
        pytest.param(
            "key = ENG-1 order by key) or (project = OPS", id="stray-parenthesis-after-order-by"
        ),
    ],
)
def test_build_jql_with_raw_jql_reaching_outside_its_group_raises(raw_jql: str) -> None:
    """Raw JQL that closes the wrapper would put ``project = OPS`` outside the project scope."""
    with pytest.raises(ValueError, match="Raw query"):
        build_jql(project_keys=["ENG"], raw_jql=raw_jql)


@pytest.mark.parametrize(
    ("raw_jql", "expected"),
    [
        pytest.param(
            'text ~ "order by"',
            'project in ("ENG") and (text ~ "order by") order by updated ASC, key ASC',
            id="double-quoted-value",
        ),
        pytest.param(
            "text ~ 'order by'",
            "project in (\"ENG\") and (text ~ 'order by') order by updated ASC, key ASC",
            id="single-quoted-value",
        ),
        pytest.param(
            'text ~ "order by" ORDER BY created',
            'project in ("ENG") and (text ~ "order by") ORDER BY created',
            id="quoted-value-then-ordering",
        ),
    ],
)
def test_build_jql_with_order_by_inside_a_quoted_value_keeps_it_in_the_condition(
    raw_jql: str, expected: str
) -> None:
    assert build_jql(project_keys=["ENG"], raw_jql=raw_jql) == expected


def test_build_jql_supports_filters_without_project_keys() -> None:
    jql = build_jql(issue_types=["Bug"])
    assert 'issuetype in ("Bug")' in jql
    assert "project in" not in jql


def test_build_jql_escapes_text_search_instead_of_treating_it_as_raw_jql() -> None:
    """The payload stays inside one escaped literal, never as unquoted JQL."""
    jql = build_jql(project_keys=["ENG"], text_search='" OR project = "OPS')

    assert 'project in ("ENG")' in jql
    assert 'text ~ "\\" OR project = \\"OPS"' in jql
    assert 'OR project = "OPS"' not in jql.replace('\\"', "")


def test_jql_from_query_treats_pattern_as_safe_text_search_not_raw_jql() -> None:
    connector = JiraConnector(cloud_config(), client=FakeJiraClient())

    jql = connector._jql_from_query(ConnectorQuery(pattern='" OR project = "OPS'))

    assert 'project in ("ENG")' in jql
    assert 'text ~ "\\" OR project = \\"OPS"' in jql


def test_search_body_without_expand_omits_it() -> None:
    body = search_body(jql="x", start_at=0, max_results=10, fields=("summary",))
    assert "expand" not in body
