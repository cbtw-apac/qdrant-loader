"""Title-to-page-id resolution for Confluence ``ac:link`` targets."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest

from harborrag_adapters.connectors.confluence.title_resolution import (
    PageTitleResolver,
    _title_digest,
)

pytestmark = [pytest.mark.unit, pytest.mark.whitebox]


@dataclass(frozen=True, slots=True)
class _Config:
    """The one ConfluenceSpaceConfig field the resolver reads."""

    space_key: str = "ENG"


class _RateLimited(RuntimeError):
    """The 429 the live token took mid-session, as a named condition."""


class _Content:
    """Stand in for ConfluenceContentAPI.search, recording every CQL issued."""

    def __init__(self, results: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self.config = _Config()
        self.queries: list[str] = []
        self._results = results or {}

    def search(self, cql: str) -> Iterator[dict[str, Any]]:
        self.queries.append(cql)
        yield from self._results.get(cql, [])


class _Failing(_Content):
    def search(self, cql: str) -> Iterator[dict[str, Any]]:
        self.queries.append(cql)
        raise _RateLimited
        yield  # pragma: no cover - generator marker


class _FailsOnce(_Content):
    """Rate-limit the first search, then behave like a healthy instance."""

    def search(self, cql: str) -> Iterator[dict[str, Any]]:
        self.queries.append(cql)
        if len(self.queries) == 1:
            raise _RateLimited
        yield from self._results.get(cql, [])


def _resolver(content: _Content) -> PageTitleResolver:
    return PageTitleResolver(content)  # type: ignore[arg-type]  # duck-typed ConfluenceContentAPI


def test_a_title_resolves_to_the_page_id_the_graph_keys_pages_by() -> None:
    cql = 'space = "ENG" and title = "Deploy Runbook" and type = page'
    content = _Content({cql: [{"id": "8891", "title": "Deploy Runbook"}]})

    assert _resolver(content).page_id_for_title("ENG", "Deploy Runbook") == "8891"
    assert content.queries == [cql]


def test_each_title_costs_one_lookup_however_often_it_appears() -> None:
    cql = 'space = "ENG" and title = "Deploy Runbook" and type = page'
    content = _Content({cql: [{"id": "8891"}]})
    resolver = _resolver(content)

    for _ in range(4):
        assert resolver.page_id_for_title("ENG", "Deploy Runbook") == "8891"

    assert content.queries == [cql]


def test_an_unresolvable_title_is_cached_too() -> None:
    """173 references over 48 distinct titles: without negative caching, the 22 titles
    that belong to other spaces would be re-queried on every occurrence."""

    content = _Content()
    resolver = _resolver(content)

    assert resolver.page_id_for_title("ENG", "Elsewhere") is None
    assert resolver.page_id_for_title("ENG", "Elsewhere") is None

    assert len(content.queries) == 1


def test_a_lookup_failure_degrades_instead_of_failing_the_document() -> None:
    """The token 403'd mid-session once already. A link that cannot be resolved must
    leave the page ingestible, exactly as it was before titles were read at all."""

    content = _Failing()

    assert _resolver(content).page_id_for_title("ENG", "Deploy Runbook") is None


def test_a_non_numeric_id_is_not_accepted_as_a_page_id() -> None:
    cql = 'space = "ENG" and title = "Odd" and type = page'
    content = _Content({cql: [{"id": "not-a-page-id"}]})

    assert _resolver(content).page_id_for_title("ENG", "Odd") is None


def test_the_title_is_quoted_into_the_cql_rather_than_interpolated_raw() -> None:
    """The raw quote must not survive unescaped into the CQL expression."""
    content = _Content()

    _resolver(content).page_id_for_title("ENG", 'Weird " title')

    assert content.queries
    assert '"' in content.queries[0]
    assert 'title = "Weird " title"' not in content.queries[0]


def test_a_failed_lookup_is_not_cached_as_a_missing_title() -> None:
    """A 429 on the first reference must not unresolve every later one.

    Caching the failure would pin the title as unresolved for the lifetime of the
    connector, so one transient rate limit would cost the graph every edge to that page
    in the run rather than the single reference that hit it.
    """

    cql = 'space = "ENG" and title = "Deploy Runbook" and type = page'
    content = _FailsOnce({cql: [{"id": "8891"}]})
    resolver = _resolver(content)

    assert resolver.page_id_for_title("ENG", "Deploy Runbook") is None
    assert resolver.page_id_for_title("ENG", "Deploy Runbook") == "8891"
    assert content.queries == [cql, cql]


def test_a_title_in_another_space_stays_unresolved_without_a_lookup() -> None:
    """A page author must not learn which titles exist in spaces outside the connection."""
    cql = 'space = "OPS" and title = "Payroll" and type = page'
    content = _Content({cql: [{"id": "77"}]})

    assert _resolver(content).page_id_for_title("OPS", "Payroll") is None
    assert content.queries == []


def test_the_lookup_is_constrained_to_pages() -> None:
    """An unconstrained CQL search returns attachments, comments and blog posts too, and
    each carries a numeric id -- so a same-titled one would be taken for the page."""

    content = _Content()

    _resolver(content).page_id_for_title("ENG", "Deploy Runbook")

    assert content.queries == ['space = "ENG" and title = "Deploy Runbook" and type = page']


def test_a_title_never_reaches_the_log(caplog: pytest.LogCaptureFixture) -> None:
    """Both unresolved paths log once per title, and a title is document content -- on a
    customer space it carries customer names and unreleased product names. The digest is
    stable enough to count occurrences by, and cannot be read back."""

    title = "Acme Corp Q3 Incident Postmortem"
    with caplog.at_level(logging.INFO, logger="harborrag.adapters.connectors.confluence"):
        _resolver(_Content()).page_id_for_title("ENG", title)
        _resolver(_Failing()).page_id_for_title("ENG", title)

    assert len(caplog.records) == 2
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert title not in logged
    assert "Acme" not in logged
    assert logged.count(_title_digest(title)) == 2
