"""CQL, search-parameter and content-ID helpers for the Confluence connector.

Pure functions with no I/O. Every caller-supplied value reaches CQL through
``quote_cql`` or ``validate_token``; the one exception, ``build_cql``'s raw CQL,
is held inside the configured space by ``require_self_contained_query``. That
space is a tenant-isolation boundary, not a convenience default.

Start from: build_cql, build_search_params.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

from harborrag_adapters.connectors.atlassian.query import is_cloud_hostname as is_cloud_hostname
from harborrag_adapters.connectors.atlassian.query import require_self_contained_query

CONTENT_EXPAND = (
    "body.storage,body.export_view,version,metadata.labels,history,space,"
    "extensions.position,ancestors,children.page"
)
CLOUD_CONTENT_EXPAND = f"body.atlas_doc_format,{CONTENT_EXPAND}"
LIGHT_EXPAND = "version,metadata.labels,space"
DESCRIPTOR_EXPAND = "version,metadata.labels,history,space,ancestors,children.page"
COMMENT_EXPAND = "body.storage,history"
DEFAULT_PAGE_SIZE = 25

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_CONTENT_ID_RE = re.compile(r"^[0-9]+$")
_DEFAULT_CQL = 'type in ("page","blogpost")'


def format_query_timestamp(value: datetime) -> str:
    """Render a datetime as the UTC ``yyyy/MM/dd HH:mm`` timestamp CQL compares against.

    Confluence reads a bare CQL timestamp in the API user's timezone, so a local
    render would shift the incremental-sync watermark by that offset and miss or
    re-ingest documents. Deployments must set the integration account's timezone
    to UTC, ideally with a safety-overlap window, for exact incremental behaviour.

    Args:
        value: Watermark to render; a naive value is taken as UTC.

    Returns:
        The watermark as ``yyyy/MM/dd HH:mm`` in UTC.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y/%m/%d %H:%M")


def extract_cursor(next_url: str | None) -> str | None:
    """Return the Cloud pagination cursor from a search response's next link, if any."""
    if not next_url:
        return None
    values = parse_qs(urlparse(next_url).query).get("cursor")
    return values[0] if values else None


def quote_cql(value: str) -> str:
    """Quote a CQL literal with the escaping Confluence expects."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def validate_token(value: str, *, field_name: str) -> str:
    """Return a space key, content type or label that is safe to put in CQL.

    Args:
        value: Token to check.
        field_name: What the token is, named in the error message.

    Returns:
        ``value`` unchanged.

    Raises:
        ValueError: ``value`` holds anything but letters, digits, underscore and hyphen.
    """
    if not _TOKEN_RE.fullmatch(value):
        raise ValueError(
            f"Invalid Confluence {field_name}: only letters, numbers, "
            "underscore and hyphen are allowed."
        )
    return value


def validate_content_id(value: str) -> str:
    """Return a content ID that is safe to put in a Confluence REST path.

    Args:
        value: Content ID; surrounding whitespace is removed.

    Returns:
        The ID without surrounding whitespace.

    Raises:
        ValueError: The ID is not all digits.
    """
    normalized = str(value).strip()
    if not _CONTENT_ID_RE.fullmatch(normalized):
        raise ValueError("Invalid Confluence content ID: expected digits only")
    return normalized


def build_cql(
    *,
    space_key: str | None = None,
    content_types: Sequence[str] | None = None,
    labels: Sequence[str] | None = None,
    updated_after: datetime | None = None,
    text_search: str | None = None,
    raw_cql: str | None = None,
) -> str:
    """Build the CQL search expression for one discovery query.

    The filters are allowlisted tokens joined with ``and``; ``text_search`` is
    always escaped into a ``text ~ "..."`` clause and never read as CQL. Only
    ``raw_cql`` skips the type and label allowlists, for callers that need full
    CQL, and even then the space stays mandatory: ``raw_cql`` must be one
    self-contained expression and is ANDed with ``space = <space_key>`` at the
    top level, so it can never reach another space. The ``ValueError`` of
    ``validate_token`` or ``require_self_contained_query`` passes through when a
    space key, content type or label is malformed, or when ``raw_cql`` could
    reach outside its parentheses.

    Args:
        space_key: The connection's configured space; the caller has already
            checked that the query asks for no other space.
        content_types: Content types to match, such as ``page``.
        labels: Labels of which the content must carry at least one.
        updated_after: Incremental-sync watermark.
        text_search: Free-text term, always escaped.
        raw_cql: Full CQL used instead of the other filters, kept inside
            ``space_key`` when one is given.

    Returns:
        The CQL expression; pages and blog posts when no filter is given.
    """
    if raw_cql:
        if not space_key:
            return raw_cql
        safe_space = validate_token(space_key, field_name="space key")
        return f"({require_self_contained_query(raw_cql)}) and space = {quote_cql(safe_space)}"

    clauses: list[str] = []
    if space_key:
        safe_space = validate_token(space_key, field_name="space key")
        clauses.append(f"space = {quote_cql(safe_space)}")
    if content_types:
        safe_types = [
            quote_cql(validate_token(value, field_name="content type")) for value in content_types
        ]
        clauses.append(f"type in ({','.join(safe_types)})")
    if labels:
        safe_labels = [quote_cql(validate_token(value, field_name="label")) for value in labels]
        clauses.append(f"label in ({','.join(safe_labels)})")
    if updated_after:
        clauses.append(f"lastmodified >= {quote_cql(format_query_timestamp(updated_after))}")
    if text_search:
        clauses.append(f"text ~ {quote_cql(text_search)}")

    return " and ".join(clauses) or _DEFAULT_CQL


def build_search_params(
    *,
    cql: str,
    limit: int = DEFAULT_PAGE_SIZE,
    start: int | None = None,
    cursor: str | None = None,
    expand: str = LIGHT_EXPAND,
) -> dict[str, str | int]:
    """Build the query parameters of one Confluence ``content/search`` page.

    Args:
        cql: Search expression from ``build_cql``.
        limit: Results per page.
        start: Data Center result offset; ignored when ``cursor`` is given.
        cursor: Cloud cursor from ``extract_cursor``.
        expand: Fields to expand on each result.

    Returns:
        The search query parameters, paged by cursor when one is given.
    """
    params: dict[str, str | int] = {"cql": cql, "limit": limit, "expand": expand}
    if cursor:
        params["cursor"] = cursor
    elif start is not None:
        params["start"] = start
    return params
