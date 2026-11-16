"""Unit tests for Confluence connector CQL/timestamp/hostname utility helpers."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from confluence_test_helpers import DC_BASE

from harborrag_adapters.connectors.confluence import ConfluenceDeploymentType
from harborrag_adapters.connectors.confluence.mappers import (
    content_id_from_record,
    display_url,
)
from harborrag_adapters.connectors.confluence.mappers import (
    parse_timestamp as mapper_parse_timestamp,
)
from harborrag_adapters.connectors.confluence.query import (
    build_cql,
    build_search_params,
    format_query_timestamp,
    is_cloud_hostname,
)
from harborrag_core.domain.source import SourceRecord

pytestmark = [pytest.mark.unit, pytest.mark.whitebox]


def test_build_cql_supports_incremental_sync_and_rejects_unsafe_tokens() -> None:
    cql = build_cql(
        space_key="ENG",
        content_types=["page"],
        labels=["runbook"],
        updated_after=datetime(2024, 1, 2, 3, 4, tzinfo=UTC),
    )

    assert 'space = "ENG"' in cql
    assert 'type in ("page")' in cql
    assert 'label in ("runbook")' in cql
    assert 'lastmodified >= "2024/01/02 03:04"' in cql
    with pytest.raises(ValueError, match="Invalid Confluence space key"):
        build_cql(space_key='ENG" OR space = "OTHER')


def test_is_cloud_hostname_with_malformed_url_returns_false() -> None:
    assert is_cloud_hostname("http://[invalid") is False


def test_format_query_timestamp_assumes_utc_for_naive_datetime() -> None:
    naive = datetime(2024, 1, 2, 3, 4)
    assert format_query_timestamp(naive) == "2024/01/02 03:04"


def test_build_cql_with_raw_cql_and_no_space_returns_it_verbatim() -> None:
    assert build_cql(raw_cql="type = page") == "type = page"


def test_build_cql_with_raw_cql_ands_the_configured_space_at_the_top_level() -> None:
    """Raw CQL skips the type and label allowlists but never the configured space."""
    cql = build_cql(space_key="ENG", raw_cql='type = page or space = "OTHER"')

    assert cql == '(type = page or space = "OTHER") and space = "ENG"'


def test_build_cql_with_raw_cql_closing_its_group_raises() -> None:
    """The issue #106 payload would leave ``space = "OTHER"`` outside the space scope."""
    with pytest.raises(ValueError, match="Raw query"):
        build_cql(space_key="ENG", raw_cql='space = "OTHER") or (space = "ENG"')


def test_build_cql_without_space_key_or_content_types_uses_only_given_filters() -> None:
    cql = build_cql(labels=["runbook"])
    assert cql == 'label in ("runbook")'


def test_build_cql_escapes_text_search_instead_of_treating_it_as_raw_cql() -> None:
    cql = build_cql(space_key="ENG", text_search='" OR space = "OTHER')

    assert 'space = "ENG"' in cql
    assert 'text ~ "\\" OR space = \\"OTHER"' in cql
    assert 'OR space = "OTHER"' not in cql.replace('\\"', "")


def test_build_search_params_without_cursor_or_start_omits_both() -> None:
    params = build_search_params(cql="type=page")
    assert "cursor" not in params
    assert "start" not in params


def test_parse_timestamp_with_missing_or_invalid_value_returns_none() -> None:
    assert mapper_parse_timestamp(None) is None
    assert mapper_parse_timestamp("not-a-timestamp") is None


def test_content_id_from_record_without_content_id_raises() -> None:
    record = SourceRecord("confluence://ENG/x", "text/html", "")
    record.metadata.pop("content_id", None)
    with pytest.raises(ValueError, match="does not contain content_id"):
        content_id_from_record(record)


def test_content_id_from_record_with_path_fragments_raises() -> None:
    record = SourceRecord("confluence://ENG/1", "text/html", "1/child/page")

    with pytest.raises(ValueError, match="content ID"):
        content_id_from_record(record)


def test_display_url_for_datacenter_uses_display_path() -> None:
    url = display_url(DC_BASE, ConfluenceDeploymentType.DATACENTER, "ENG", "1", "Page One")
    assert url == f"{DC_BASE}/display/ENG/Page+One"
