"""Query helpers shared by the Confluence and Jira connectors.

Pure functions with no I/O. Both connectors scope caller-supplied raw CQL or JQL
by wrapping it as ``(raw) and <scope>``; ``require_self_contained_query`` keeps
that wrapper a top-level AND, so the configured space or projects stay a
tenant-isolation boundary rather than a default.

Start from: require_self_contained_query, is_cloud_hostname.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

_QUERY_STRUCTURE_RE = re.compile(
    r"""
    "(?:[^"\\]|\\.)*"   # a closed double-quoted value; a backslash escapes the next character
    | '[^'\\()"]*'      # a closed single-quoted value without \, (, ) or "
    | [()"'\\]          # a parenthesis, an unclosed quote or a backslash outside double quotes
    """,
    re.VERBOSE | re.DOTALL,
)
_UNSAFE_TOKENS = frozenset({'"', "'", "\\"})
_DEPTH_CHANGE = {"(": 1, ")": -1}
_NOT_SELF_CONTAINED = (
    "Raw query must close every parenthesis and quoted value it opens, never close a "
    "parenthesis it did not open, use a backslash only inside double quotes, and keep "
    "parentheses and double quotes out of single-quoted values"
)


def is_cloud_hostname(base_url: str) -> bool:
    """Return whether a base URL looks like Atlassian Cloud."""
    try:
        hostname = urlparse(str(base_url)).hostname
    except ValueError:
        return False
    return bool(hostname and hostname.endswith(".atlassian.net"))


def require_self_contained_query(raw: str) -> str:
    """Reject raw CQL or JQL that could reach outside the parentheses it is wrapped in.

    The connectors scope raw text as ``(raw) and <scope>``. Atlassian binds AND
    tighter than OR, so a ``raw`` that closes the wrapper early, such as
    ``x) or (space = "OTHER"``, would leave the scope guarding only its last branch.
    Double-quoted values are read as CQL and JQL read them, with backslash
    escapes. A single-quoted value may not hold a backslash, a parenthesis or a
    double quote, and a backslash is rejected anywhere else: Atlassian does not
    document these cases for every deployment, so only text that splits into the
    same groups whether or not ``'`` delimits a value gets through.

    Args:
        raw: Caller-supplied CQL or JQL condition, without an ORDER BY clause.

    Returns:
        ``raw`` unchanged.

    Raises:
        ValueError: ``raw`` closes a parenthesis it did not open, leaves a
            parenthesis or quoted value open, has a backslash outside double
            quotes, or has a parenthesis or double quote in single quotes.
    """
    if not _is_self_contained(raw):
        raise ValueError(_NOT_SELF_CONTAINED)
    return raw


def _is_self_contained(raw: str) -> bool:
    """Return whether every parenthesis and quote in ``raw`` is opened and closed inside it."""
    depth = 0
    for token in _QUERY_STRUCTURE_RE.findall(raw):
        if token in _UNSAFE_TOKENS:
            return False
        depth += _DEPTH_CHANGE.get(token, 0)
        if depth < 0:
            return False
    return depth == 0
