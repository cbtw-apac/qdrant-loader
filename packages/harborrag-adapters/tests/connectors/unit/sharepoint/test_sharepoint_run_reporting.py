"""Unit tests for SharePoint run IDs, logs, startup auth and author metadata."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

import pytest
from sharepoint_test_helpers import (
    SITE_URL,
    FakeGraphClient,
    add_site_and_default_drive,
    config,
    drive,
    file_item,
    site,
)

from harborrag_adapters.connectors import SharePointConnector, SharePointSiteConfig
from harborrag_adapters.connectors.exceptions import (
    AuthenticationError,
    AuthorizationError,
    FetchError,
)
from harborrag_adapters.connectors.sharepoint.mappers import (
    build_document_metadata,
    build_source_record,
    parse_timestamp,
)
from harborrag_adapters.connectors.sharepoint.skips import (
    SharePointItemMissingError,
    SharePointItemSkippedError,
)
from harborrag_core.domain.source import SourceRecord

pytestmark = [pytest.mark.unit, pytest.mark.graybox]

_LOGGER = "harborrag.adapters.connectors.sharepoint"
_CV_NAME = "Alex-Example-CV.docx"
_CV_URL = f"{SITE_URL}/Shared%20Documents/{_CV_NAME}"


class _RaisingGraphClient(FakeGraphClient):
    def __init__(self, errors: dict[str, Exception]) -> None:
        super().__init__()
        self.errors = errors

    def get_json(self, endpoint: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if endpoint in self.errors:
            self.calls.append((endpoint, params))
            raise self.errors[endpoint]
        return super().get_json(endpoint, params=params)

    def get_bytes(self, endpoint: str) -> bytes:
        if endpoint in self.errors:
            self.byte_calls.append(endpoint)
            raise self.errors[endpoint]
        return super().get_bytes(endpoint)


def _events(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    """Return the JSON log entries, skipping plain-text debug lines."""
    messages = [record.getMessage() for record in caplog.records if record.name == _LOGGER]
    return [json.loads(message) for message in messages if message.startswith("{")]


def _logged_text(caplog: pytest.LogCaptureFixture) -> str:
    """Return every captured message together with each record's attributes and extras."""
    return "\n".join(f"{record.getMessage()}\n{vars(record)}" for record in caplog.records)


def _file_record(item_id: str) -> SourceRecord:
    return SourceRecord(
        f"sharepoint://site1/drive1/{item_id}",
        "application/octet-stream",
        item_id,
        metadata={"drive_id": "drive1", "item_id": item_id},
    )


def _discover_with_one_skip(connector: SharePointConnector, client: FakeGraphClient) -> None:
    add_site_and_default_drive(client)
    client.add(
        "drives/drive1/root:/Docs:/children",
        {"value": [file_item("file1", "Guide.docx"), file_item("big", _CV_NAME, size=99)]},
    )
    list(connector.discover())


def test_discover_bound_run_id_tags_skip_and_summary_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = FakeGraphClient()
    connector = SharePointConnector(config(root_path="Docs", max_file_size_bytes=50), client=client)
    connector.bind_run_id("task-42")

    with caplog.at_level(logging.INFO, logger=_LOGGER):
        _discover_with_one_skip(connector, client)

    events = _events(caplog)
    skip = next(event for event in events if event["event"] == "sharepoint.item_skipped")
    assert skip == {
        "event": "sharepoint.item_skipped",
        "run_id": "task-42",
        "skip_reason": "EXCEEDS_SIZE_LIMIT",
        "item_id": "big",
    }
    summary = next(event for event in events if event["event"] == "sharepoint.discovery_summary")
    assert summary == {
        "event": "sharepoint.discovery_summary",
        "run_id": "task-42",
        "discovered": 1,
        "skipped": 1,
        "skipped_by_reason": {"EXCEEDS_SIZE_LIMIT": 1},
    }


def test_discover_declined_file_logs_no_file_name_or_url(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = FakeGraphClient()
    connector = SharePointConnector(config(root_path="Docs", max_file_size_bytes=50), client=client)

    with caplog.at_level(logging.DEBUG):
        _discover_with_one_skip(connector, client)

    (skip,) = connector.skipped
    assert (skip.item_id, skip.url) == ("big", _CV_URL)
    assert caplog.records
    assert _CV_NAME not in _logged_text(caplog)
    assert _CV_URL not in _logged_text(caplog)


def test_load_declined_file_logs_no_file_name_or_url(caplog: pytest.LogCaptureFixture) -> None:
    client = FakeGraphClient()
    add_site_and_default_drive(client)
    client.add("drives/drive1/items/big", file_item("big", _CV_NAME, size=99))
    connector = SharePointConnector(config(max_file_size_bytes=50), client=client)

    with caplog.at_level(logging.DEBUG), pytest.raises(SharePointItemSkippedError) as error:
        connector.load(_file_record("big"))

    assert error.value.url == _CV_URL
    assert any(event["event"] == "sharepoint.item_skipped" for event in _events(caplog))
    assert _CV_NAME not in _logged_text(caplog)


def test_load_failed_download_logs_no_file_name_or_url(caplog: pytest.LogCaptureFixture) -> None:
    client = _RaisingGraphClient(
        {"drives/drive1/items/file1/content": FetchError("gone", status_code=404)}
    )
    add_site_and_default_drive(client)
    client.add("drives/drive1/items/file1", file_item("file1", _CV_NAME))
    connector = SharePointConnector(config(), client=client)

    with caplog.at_level(logging.DEBUG), pytest.raises(SharePointItemMissingError) as error:
        connector.load(_file_record("file1"))

    assert error.value.url == _CV_URL
    assert any(event["event"] == "sharepoint.item_skipped" for event in _events(caplog))
    assert _CV_NAME not in _logged_text(caplog)


def test_connector_without_bound_run_id_gets_its_own_run_id() -> None:
    first = SharePointConnector(config(), client=FakeGraphClient())
    second = SharePointConnector(config(), client=FakeGraphClient())

    assert first.run_id and second.run_id
    assert first.run_id != second.run_id


def _site_id_config() -> SharePointSiteConfig:
    return SharePointSiteConfig(
        site_id="site1", drive_id="drive1", access_token="token", requests_per_minute=6000
    )


def test_connect_site_id_with_bad_credentials_fails_at_startup() -> None:
    client = _RaisingGraphClient(
        {"sites/site1": AuthenticationError("bad credentials", status_code=401)}
    )
    connector = SharePointConnector(_site_id_config(), client=client)

    with pytest.raises(AuthenticationError):
        connector.connect()
    assert client.calls[0][0] == "sites/site1"


def test_connect_site_id_without_grant_reports_sites_selected() -> None:
    client = _RaisingGraphClient({"sites/site1": AuthorizationError("forbidden", status_code=403)})
    connector = SharePointConnector(_site_id_config(), client=client)

    with pytest.raises(AuthorizationError, match="Sites.Selected"):
        connector.connect()


def test_discover_site_id_with_bad_credentials_fails_before_walking() -> None:
    client = _RaisingGraphClient(
        {"sites/site1": AuthenticationError("bad credentials", status_code=401)}
    )
    connector = SharePointConnector(_site_id_config(), client=client)

    with pytest.raises(AuthenticationError):
        list(connector.discover())
    assert [endpoint for endpoint, _ in client.calls] == ["sites/site1"]


def test_author_identity_set_with_user_prefers_user_over_application() -> None:
    item = file_item()
    item["createdBy"] = {
        "application": {"displayName": "Migration Tool"},
        "user": {"displayName": "Ada"},
    }

    record = build_source_record(item, site_id="site1", drive_id="drive1")
    metadata = build_document_metadata(item, site=site(), drive=drive(), checksum="sum")

    assert record.metadata["author"] == "Ada"
    assert metadata.author == "Ada"


def test_parse_timestamp_offset_or_utc_suffix_returns_utc() -> None:
    assert parse_timestamp("2024-05-24T22:57:56+02:00") == datetime(
        2024, 5, 24, 20, 57, 56, tzinfo=UTC
    )
    assert parse_timestamp("2024-05-24T20:57:56Z").tzinfo is UTC
