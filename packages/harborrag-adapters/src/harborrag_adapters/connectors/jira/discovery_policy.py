"""Jira discovery policy: which issues a query may reach and what each record carries.

Owns the connection's project boundary. Query filters may narrow the configured
projects but never leave them, and every fetched issue is checked against them
again, so neither raw JQL nor an explicit key can pull another project's issues in.
The only request made here is the permission probe behind an empty search.

Start from: JiraDiscoveryPolicy, issue_keys_from_query, verify_empty_search_result.
"""

from __future__ import annotations

import logging
from typing import Any

from harborrag_adapters.connectors.attachments import attachment_ids_from_filters
from harborrag_adapters.connectors.exceptions import (
    AuthorizationError,
    DocumentProcessingError,
    FetchError,
)
from harborrag_adapters.connectors.query_values import normalized_string_list
from harborrag_adapters.connectors.schemas import ConnectorQuery
from harborrag_core.domain.source import SourceRecord

from .config import JiraProjectConfig
from .issues import JiraIssueAPI
from .mappers import issue_url
from .query import build_jql, validate_issue_key


def issue_keys_from_query(query: ConnectorQuery) -> list[str]:
    """Return the explicit issue keys a query asks for, validated.

    The ``ValueError`` of ``validate_issue_key`` passes through for a malformed key.

    Args:
        query: Discovery query whose ``issue_keys`` or ``keys`` filter names issues.

    Returns:
        The validated keys; empty when the query names none.
    """
    values = query.filters.get("issue_keys") or query.filters.get("keys")
    if values is None:
        return []
    if isinstance(values, str):
        return [validate_issue_key(values)]
    return [validate_issue_key(str(value)) for value in values]


class JiraDiscoveryPolicy:
    """Bound Jira discovery to the configured projects and shape its records.

    Args:
        config: The connection's validated Jira configuration.
        base_url: Jira base URL that issue links are built from.
    """

    def __init__(self, config: JiraProjectConfig, *, base_url: str) -> None:
        self._config = config
        self._base_url = base_url

    def effective_project_keys(self, query: ConnectorQuery) -> list[str]:
        """Return the projects a search is bounded to.

        A query's ``project_keys``, ``project_key`` or path narrows the configured
        projects; without one, the configured projects apply. A connection that
        configures no projects leaves the query free to name any.

        Args:
            query: Discovery query.

        Returns:
            The project keys the search must stay inside; empty for no bound.

        Raises:
            ValueError: The query names a project outside the configured ones.
        """
        filters = query.filters
        requested = normalized_string_list(
            filters.get("project_keys") or filters.get("project_key") or query.path or None,
            default=[],
        )
        if not requested:
            return list(self._config.project_keys)
        if self._config.project_keys and not set(requested) <= set(self._config.project_keys):
            raise ValueError(
                "Jira query projects must stay inside the configured connection projects"
            )
        return requested

    def jql(self, query: ConnectorQuery) -> str:
        """Build the JQL search for one discovery query, bounded to its projects.

        Unset filters fall back to the configured issue types, statuses and labels.
        The ``ValueError`` of ``effective_project_keys`` or ``build_jql`` passes
        through for a project outside the configured ones or unsafe raw JQL.

        Args:
            query: Discovery query.

        Returns:
            The JQL search.
        """
        filters = query.filters
        return build_jql(
            project_keys=self.effective_project_keys(query),
            issue_types=normalized_string_list(
                filters.get("issue_types") or filters.get("issue_type"),
                default=self._config.issue_types,
            ),
            statuses=normalized_string_list(
                filters.get("statuses") or filters.get("status"),
                default=self._config.statuses,
            ),
            labels=normalized_string_list(
                filters.get("labels") or filters.get("label"),
                default=self._config.labels,
            ),
            updated_after=query.updated_after,
            text_search=query.pattern,
            raw_jql=filters.get("jql"),
        )

    def record_for_key(self, issue_key: str, query: ConnectorQuery) -> SourceRecord:
        """Build the discovery record for one explicit issue key.

        The ``ValueError`` of ``validate_issue_key`` passes through for a malformed
        key, and the ``DocumentProcessingError`` of the project check for a key in a
        project outside the configured ones.

        Args:
            issue_key: Issue key such as ``ENG-123``.
            query: Discovery query whose per-record options the record carries.

        Returns:
            The record, with the query's attachment, comment and graph options applied.
        """
        issue_key = validate_issue_key(issue_key)
        project_key = issue_key.split("-", 1)[0]
        self._check_project_scope(project_key, issue_key)
        return self.apply_query(
            SourceRecord(
                id=f"jira://{project_key}/{issue_key}",
                source_type="application/vnd.atlassian.jira.issue+json",
                locator=issue_key,
                metadata={
                    "issue_key": issue_key,
                    "project_key": project_key,
                    "url": issue_url(self._base_url, issue_key),
                    "include_attachments": query.include_attachments,
                },
            ),
            query,
        )

    @staticmethod
    def apply_query(record: SourceRecord, query: ConnectorQuery) -> SourceRecord:
        """Copy a query's per-record options onto a discovery record.

        Args:
            record: Record to update in place.
            query: Discovery query carrying the attachment, comment and graph options.

        Returns:
            The same record.
        """
        record.metadata["include_attachments"] = query.include_attachments
        record.metadata["include_comments"] = bool(query.filters.get("include_comments", True))
        record.metadata["build_graph"] = bool(query.filters.get("build_graph", True))
        selected = attachment_ids_from_filters(query.filters)
        if selected:
            record.metadata["_selected_attachment_ids"] = selected
        return record

    def validate_issue(self, issue: dict[str, Any], issue_key: str) -> None:
        """Fail fast on an issue payload that is malformed or outside the configured projects.

        Args:
            issue: Issue payload from the Jira search or issue API.
            issue_key: Key the issue is reported under in errors.

        Raises:
            DocumentProcessingError: The payload lacks its id, key or summary, or the
                issue belongs to a project outside the configured ones.
        """
        fields = issue.get("fields", {})
        missing = [
            name
            for name, value in (
                ("id", issue.get("id")),
                ("key", issue.get("key")),
                ("fields.summary", fields.get("summary")),
            )
            if not value
        ]
        if missing:
            raise DocumentProcessingError(
                f"JIRA issue {issue_key} missing required fields: {', '.join(missing)}"
            )
        self._check_project_scope(fields.get("project", {}).get("key"), issue_key)

    def _check_project_scope(self, project_key: str | None, issue_key: str) -> None:
        """Raise ``DocumentProcessingError`` when an issue's project is not configured."""
        if self._config.project_keys and project_key not in self._config.project_keys:
            raise DocumentProcessingError(
                f"JIRA issue {issue_key} belongs to project {project_key!r}, "
                f"outside configured projects {self._config.project_keys!r}"
            )


def verify_empty_search_result(
    query: ConnectorQuery,
    *,
    policy: JiraDiscoveryPolicy,
    issues: JiraIssueAPI,
    logger_: logging.Logger,
) -> None:
    """Rule out a permission gap behind a zero-issue search result.

    ``JiraConnector.connect()`` only proves the credential holds a valid session; it
    cannot catch a credential that authenticates fine but lacks BROWSE_PROJECTS on
    the projects actually searched, because Jira's search answers that case with
    HTTP 200 and an empty result set instead of an error. The check runs here, once
    per empty result, rather than eagerly in ``connect()``, because the projects are
    per query (``project_keys``, ``project_key`` or path filters).

    Only a definitive ``havePermission: false`` raises: a valid credential that lacks
    scope is an authorization failure, not an authentication one, and a truly bad
    credential still surfaces through the shared client's 401/403 handling on this
    call. An inconclusive probe (a ``FetchError``: endpoint disabled, unknown
    permission key, transient failure) leaves the empty result standing, so a
    genuinely empty project is never reported as an authorization failure.

    Args:
        query: The query whose search came back empty.
        policy: Policy that bounded the search to its projects.
        issues: Issue API that runs the permission probe.
        logger_: Logger that records an inconclusive probe.

    Raises:
        AuthorizationError: The credential lacks BROWSE_PROJECTS on every searched project.
    """
    project_keys = policy.effective_project_keys(query)
    if not project_keys:
        return
    try:
        permitted = any(issues.has_project_permission(key) for key in project_keys)
    except FetchError:
        logger_.warning(
            "JIRA permission probe inconclusive for projects=%r; "
            "treating empty search result as genuine",
            project_keys,
        )
        return
    if permitted:
        return
    raise AuthorizationError(
        f"JIRA credential lacks BROWSE_PROJECTS permission on {project_keys!r}"
    )
