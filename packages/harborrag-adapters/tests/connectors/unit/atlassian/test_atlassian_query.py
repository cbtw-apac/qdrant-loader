"""Unit tests for the raw CQL/JQL guard shared by the Confluence and Jira connectors."""

from __future__ import annotations

import pytest

from harborrag_adapters.connectors.atlassian.query import require_self_contained_query

pytestmark = [pytest.mark.unit, pytest.mark.whitebox]


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param(
            'creator = currentUser() and type in ("page","blogpost")', id="function-and-list"
        ),
        pytest.param('((type = page or type = blogpost) and label = "runbook")', id="nested"),
        pytest.param('title ~ "a ) or ( b"', id="parentheses-inside-double-quotes"),
        pytest.param("space = 'ENG' and title ~ 'run book'", id="single-quoted-values"),
        pytest.param('title ~ "say \\"hi\\" (twice)"', id="escaped-double-quotes"),
        pytest.param('text ~ "\\\\(text"', id="escaped-backslash"),
    ],
)
def test_require_self_contained_query_with_one_expression_returns_it_unchanged(raw: str) -> None:
    assert require_self_contained_query(raw) == raw


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param('space = "OTHER") or (space = "ENG"', id="closes-the-wrapping-group"),
        pytest.param("type = page)", id="stray-closing-parenthesis"),
        pytest.param("(type = page", id="unclosed-parenthesis"),
        pytest.param('title ~ "open', id="unclosed-double-quote"),
        pytest.param("title ~ 'open", id="unclosed-single-quote"),
        pytest.param('title ~ "ends in an escaped quote\\"', id="escaped-closing-quote"),
        pytest.param("title ~ 'a\\' ) or (space = OTHER'", id="backslash-in-single-quotes"),
        pytest.param("title ~ 'a ) or ( b'", id="parentheses-in-single-quotes"),
        pytest.param(
            "x = '\"' ( y = '\"' ) or (space = OTHER) or (z = '\"' ) w = '\"'",
            id="double-quote-in-single-quotes",
        ),
        pytest.param("title ~ a\\(b\\)", id="backslash-outside-quotes"),
    ],
)
def test_require_self_contained_query_with_text_outside_its_group_raises(raw: str) -> None:
    with pytest.raises(ValueError, match="Raw query"):
        require_self_contained_query(raw)
