"""JQL, search-body and key helpers for the Jira connector.

Pure functions with no I/O. Every caller-supplied value reaches JQL through
``quote_jql`` or a key validator; the one exception, ``build_jql``'s raw JQL, is
held inside the given projects by ``require_self_contained_query``.

Start from: build_jql, narrow_jql, search_jql_body, search_body.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime

from harborrag_adapters.connectors.atlassian.query import is_cloud_hostname as is_cloud_hostname
from harborrag_adapters.connectors.atlassian.query import require_self_contained_query

_PROJECT_RE = re.compile(r"^[A-Z][A-Z0-9_]+$")
_ISSUE_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]+-[1-9][0-9]*$")
_QUOTED_VALUE_OR_ORDER_BY_RE = re.compile(
    r""""(?:[^"\\]|\\.)*"|'[^']*'|(?P<order_by>\border\s+by\b)""",
    re.IGNORECASE | re.DOTALL,
)
_DEFAULT_ORDERING = "order by updated ASC, key ASC"


def format_query_timestamp(value: datetime) -> str:
    """Render a datetime as the UTC ``yyyy/MM/dd HH:mm`` timestamp JQL compares against.

    Jira reads a bare JQL timestamp in the API user's timezone; normalizing to UTC
    keeps the incremental-sync watermark from drifting by that offset. Deployments
    should set the integration account's timezone to UTC.

    Args:
        value: Watermark to render; a naive value is taken as UTC.

    Returns:
        The watermark as ``yyyy/MM/dd HH:mm`` in UTC.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y/%m/%d %H:%M")


def quote_jql(value: str) -> str:
    """Quote a JQL literal with the escaping Jira expects."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def validate_project_key(value: str) -> str:
    """Return a project key that is safe to put in generated JQL.

    Args:
        value: Project key to check.

    Returns:
        ``value`` unchanged.

    Raises:
        ValueError: ``value`` is not uppercase letters, digits and underscores
            starting with a letter.
    """
    if not _PROJECT_RE.fullmatch(value):
        raise ValueError(
            "Invalid JIRA project key: expected uppercase letters, numbers, "
            "or underscore, starting with a letter."
        )
    return value


def validate_issue_key(value: str) -> str:
    """Return an issue key that is safe to put in a Jira REST path.

    Args:
        value: Issue key such as ``ENG-123``; surrounding whitespace is removed.

    Returns:
        The key without surrounding whitespace.

    Raises:
        ValueError: The key is not an uppercase project key, a hyphen and a
            positive issue number.
    """
    normalized = str(value).strip()
    if not _ISSUE_KEY_RE.fullmatch(normalized):
        raise ValueError(
            "Invalid JIRA issue key: expected PROJECT-123 with an uppercase "
            "project key and positive numeric issue number."
        )
    return normalized


def build_jql(  # noqa: PLR0913 - explicit allowlisted JQL clauses stay auditable
    *,
    project_keys: Sequence[str] | None = None,
    issue_types: Sequence[str] | None = None,
    statuses: Sequence[str] | None = None,
    labels: Sequence[str] | None = None,
    updated_after: datetime | None = None,
    text_search: str | None = None,
    raw_jql: str | None = None,
) -> str:
    """Build the deterministic JQL search for one discovery query.

    The filters are quoted values joined with ``and``; ``text_search`` is always
    escaped into a ``text ~ "..."`` clause and never read as JQL. ``raw_jql``
    replaces the other filters but not the projects: it must be one
    self-contained expression and is ANDed with ``project in (...)`` at the top
    level, so it can never reach another project. A ``ValueError`` from the
    key and raw-query checks passes through when a project key is malformed, or
    when ``raw_jql`` has nothing before its ORDER BY or could reach outside its
    parentheses.

    Args:
        project_keys: Projects the search stays inside.
        issue_types: Issue types to match.
        statuses: Statuses to match.
        labels: Labels of which the issue must carry at least one.
        updated_after: Incremental-sync watermark.
        text_search: Free-text term, always escaped.
        raw_jql: Full JQL, optionally with its own ORDER BY, used instead of the
            other filters and kept inside ``project_keys`` when any are given.

    Returns:
        The JQL search, ordered by update time and key unless ``raw_jql`` orders it.
    """
    clauses: list[str] = []
    if project_keys:
        safe_projects = [quote_jql(validate_project_key(key)) for key in project_keys]
        clauses.append(f"project in ({','.join(safe_projects)})")
    if raw_jql:
        raw = raw_jql.strip()
        return _scoped_raw_jql(raw, scope=clauses[0]) if clauses else raw
    if issue_types:
        clauses.append(f"issuetype in ({_quoted_values(issue_types)})")
    if statuses:
        clauses.append(f"status in ({_quoted_values(statuses)})")
    if labels:
        clauses.append(f"labels in ({_quoted_values(labels)})")
    if updated_after:
        clauses.append(f"updated >= {quote_jql(format_query_timestamp(updated_after))}")
    if text_search:
        clauses.append(f"text ~ {quote_jql(text_search)}")

    return f"{' and '.join(clauses)} {_DEFAULT_ORDERING}" if clauses else _DEFAULT_ORDERING


def search_body(
    *,
    jql: str,
    start_at: int,
    max_results: int,
    fields: tuple[str, ...],
    expand: tuple[str, ...] = (),
) -> dict[str, str | int | list[str]]:
    """Build the JSON body of one offset-paged ``POST /search`` page.

    ``expand`` goes in as a list of strings: the POST body rejects or ignores the
    comma-joined string that the GET query parameter takes.

    Args:
        jql: Search from ``build_jql``.
        start_at: Offset of the first result.
        max_results: Results per page.
        fields: Issue fields to return.
        expand: Issue properties to expand; left out when empty.

    Returns:
        The search request body.
    """
    body: dict[str, str | int | list[str]] = {
        "jql": jql,
        "startAt": start_at,
        "maxResults": max_results,
        "fields": list(fields),
    }
    if expand:
        body["expand"] = list(expand)
    return body


def search_jql_body(
    *,
    jql: str,
    max_results: int,
    fields: tuple[str, ...],
    next_page_token: str | None = None,
) -> dict[str, str | int | list[str]]:
    """Build the JSON body of one Jira Cloud ``POST /rest/api/3/search/jql`` page.

    Jira Cloud removed the offset-paged ``/search`` endpoint in 2025; this one
    pages with an opaque ``nextPageToken`` and returns ``isLast`` instead of a
    total. It rejects any request carrying an ``expand`` key (400 Invalid request
    payload), so the body never has one, not even an empty one.

    Args:
        jql: Search from ``build_jql``.
        max_results: Results per page.
        fields: Issue fields to return.
        next_page_token: Token from the previous page; ``None`` for the first.

    Returns:
        The search request body.
    """
    body: dict[str, str | int | list[str]] = {
        "jql": jql,
        "maxResults": max_results,
        "fields": list(fields),
    }
    if next_page_token:
        body["nextPageToken"] = next_page_token
    return body


def narrow_jql(connection_jql: str, run_jql: str) -> str:
    """AND a run's JQL onto the connection's, so a run can only narrow what the connection syncs.

    Each side is checked on its own, so neither can close the other's parentheses,
    and both conditions are ANDed at the top level. The run's ORDER BY wins;
    otherwise the connection's is kept. The ``ValueError`` of the raw-query checks
    passes through when either side has nothing before its ORDER BY or could reach
    outside its parentheses.

    Args:
        connection_jql: JQL configured on the connection.
        run_jql: JQL one run asked for.

    Returns:
        ``(<connection condition>) and (<run condition>)``, then the ORDER BY if any.
    """
    connection_condition, connection_ordering = _split_raw_jql(connection_jql.strip())
    run_condition, run_ordering = _split_raw_jql(run_jql.strip())
    ordering = run_ordering or connection_ordering
    return f"({connection_condition}) and ({run_condition}) {ordering}".strip()


def _scoped_raw_jql(raw: str, *, scope: str) -> str:
    """AND raw JQL with the project scope at the top level, keeping its ORDER BY last.

    The ``ValueError`` of ``_split_raw_jql`` passes through when ``raw`` has nothing
    before its ORDER BY or could reach outside its parentheses.

    Args:
        raw: Caller-supplied JQL, optionally ending in its own ORDER BY.
        scope: The ``project in (...)`` clause the search must stay inside.

    Returns:
        ``<scope> and (<condition>)`` followed by the raw or the default ordering.
    """
    condition, ordering = _split_raw_jql(raw)
    return f"{scope} and ({condition}) {ordering or _DEFAULT_ORDERING}"


def _split_raw_jql(raw: str) -> tuple[str, str]:
    """Split raw JQL into its self-contained condition and its ORDER BY clause.

    Both ``raw`` and its condition must be self-contained, so the ORDER BY that
    stays outside any wrapping parentheses cannot hold a stray parenthesis or quote
    either. The words ``order by`` inside a quoted value, as in
    ``text ~ "order by"``, are part of the condition. The ``ValueError`` of
    ``require_self_contained_query`` passes through when either could reach
    outside its parentheses.

    Args:
        raw: Caller-supplied JQL, optionally ending in its own ORDER BY.

    Returns:
        The condition and the ORDER BY clause, which is empty when ``raw`` has none.

    Raises:
        ValueError: ``raw`` has nothing before its ORDER BY.
    """
    require_self_contained_query(raw)
    order_by_start = _order_by_start(raw)
    if order_by_start is None:
        return raw, ""
    condition = raw[:order_by_start].strip()
    if not condition:
        raise ValueError("Raw JQL must contain a query before ORDER BY")
    return require_self_contained_query(condition), raw[order_by_start:].strip()


def _order_by_start(raw: str) -> int | None:
    """Return the offset of the first ORDER BY outside a quoted value, or ``None`` without one.

    Args:
        raw: Self-contained JQL, so every quoted value in it is closed.
    """
    for match in _QUOTED_VALUE_OR_ORDER_BY_RE.finditer(raw):
        if match.group("order_by"):
            return match.start()
    return None


def _quoted_values(values: Sequence[str]) -> str:
    """Join values as a comma-separated list of JQL literals."""
    return ",".join(quote_jql(value) for value in values)
