"""Unit tests for SharePoint connector document loading."""

from __future__ import annotations

import pytest
from sharepoint_test_helpers import (
    SITE_URL,
    FakeGraphClient,
    add_site_and_default_drive,
    config,
    file_item,
    folder_item,
)

from harborrag_adapters.connectors import SharePointConnector, SharePointSiteConfig
from harborrag_adapters.connectors.exceptions import DocumentProcessingError
from harborrag_core.domain.source import SourceRecord

pytestmark = [pytest.mark.unit, pytest.mark.graybox]

_DOWNLOAD_URL = "@microsoft.graph.downloadUrl"
_UNSAFE_ITEM_IDS = ("..", "a?b", "a:b", "a%2F..", "file1\n", "bad/file1")


def _site_id_connector(client: FakeGraphClient, **overrides: object) -> SharePointConnector:
    return SharePointConnector(
        SharePointSiteConfig(
            site_id="site1",
            drive_id="drive1",
            access_token="token",
            requests_per_minute=6000,
            **overrides,
        ),
        client=client,
    )


def _file_record(item_id: str = "file1", drive_id: str = "drive1") -> SourceRecord:
    return SourceRecord(
        f"sharepoint://site1/{drive_id}/{item_id}",
        "application/octet-stream",
        item_id,
        metadata={"drive_id": drive_id, "item_id": item_id},
    )


def test_load_file_record_downloads_content_with_metadata() -> None:
    client = FakeGraphClient()
    client.add("drives/drive1/items/file1", file_item("file1", "Guide.docx"))
    client.downloads["drives/drive1/items/file1/content"] = b"docx-bytes"
    connector = _site_id_connector(client)

    document = connector.load(_file_record())

    assert document.id == "sharepoint://site1/drive1/file1"
    assert document.content == b"docx-bytes"
    assert document.content_type.endswith("wordprocessingml.document")
    assert document.metadata["source_system"] == "sharepoint"
    assert document.metadata["metadata_schema_version"] == 1
    assert document.metadata["record_id"] == "file1"
    assert document.metadata["title"] == "Guide.docx"
    assert document.metadata["item_name"] == "Guide.docx"
    assert document.metadata["created_by"] == "Ada"
    assert document.source == f"{SITE_URL}/Shared%20Documents/Guide.docx"
    assert "web_url" not in document.metadata
    assert "site_web_url" not in document.metadata
    assert "drive_web_url" not in document.metadata
    assert "mime_type" not in document.metadata
    assert client.byte_calls == ["drives/drive1/items/file1/content"]


def test_load_file_record_never_selects_download_url() -> None:
    """Graph's ``downloadUrl`` ignores SharePoint permissions for about an hour."""
    client = FakeGraphClient()
    client.add("drives/drive1/items/file1", file_item("file1", "Guide.docx"))
    client.downloads["drives/drive1/items/file1/content"] = b"docx-bytes"
    connector = _site_id_connector(client)

    connector.load(_file_record())

    selects = [str((params or {}).get("$select", "")) for _, params in client.calls]
    assert selects and all(_DOWNLOAD_URL not in select for select in selects)


def test_load_annotated_item_drops_annotations_from_raw() -> None:
    """``raw`` is written to the immutable raw-metadata artifact as is.

    Graph can still return the pre-authenticated ``downloadUrl`` (an endpoint
    without ``$select``), so it is removed from the payload, not just unrequested.
    """
    item = file_item("file1", "Guide.docx")
    item[_DOWNLOAD_URL] = "https://tenant.sharepoint.com/_layouts/15/download.aspx?tempauth=x"
    item["@odata.etag"] = '"etag"'
    client = FakeGraphClient()
    client.add("drives/drive1/items/file1", item)
    client.downloads["drives/drive1/items/file1/content"] = b"docx-bytes"
    connector = _site_id_connector(client)

    document = connector.load(_file_record())

    assert document.raw is not None
    assert _DOWNLOAD_URL not in document.raw
    assert "tempauth" not in str(document.raw)
    assert document.raw["id"] == "file1"


def test_load_oversized_file_raises_before_download() -> None:
    client = FakeGraphClient()
    client.add("drives/drive1/items/file1", file_item("file1", "Guide.docx", size=99))
    connector = _site_id_connector(client, max_file_size_bytes=10)

    with pytest.raises(DocumentProcessingError, match="max_file_size_bytes"):
        connector.load(_file_record())
    assert client.byte_calls == []


def test_load_record_drive_outside_scope_raises_before_any_request() -> None:
    """The drive scope check rejects the record before any Graph call for the item."""
    client = FakeGraphClient()
    connector = _site_id_connector(client)

    with pytest.raises(DocumentProcessingError, match="outside configured drive"):
        connector.load(_file_record(drive_id="other-drive"))
    assert client.calls == []
    assert client.byte_calls == []


def test_load_folder_record_raises() -> None:
    client = FakeGraphClient()
    client.add("drives/drive1/items/folder1", folder_item())
    connector = _site_id_connector(client)

    with pytest.raises(DocumentProcessingError, match="not a downloadable file"):
        connector.load(SourceRecord("sharepoint://site1/drive1/folder1", "folder", "folder1"))


@pytest.mark.parametrize("item_id", _UNSAFE_ITEM_IDS)
def test_load_record_with_unsafe_item_id_raises_before_any_request(item_id: str) -> None:
    client = FakeGraphClient()
    connector = _site_id_connector(client)

    with pytest.raises(ValueError, match="drive item ID"):
        connector.load(_file_record(item_id))
    assert client.calls == []
    assert client.byte_calls == []


def test_load_record_outside_root_path_raises_before_download() -> None:
    item = file_item("file1", "A.docx")
    item["parentReference"]["path"] = "/drive/root:/Secrets"
    client = FakeGraphClient()
    client.add("drives/drive1/items/file1", item)
    client.downloads["drives/drive1/items/file1/content"] = b"bytes-a"
    connector = _site_id_connector(client, root_path="Docs")

    with pytest.raises(ValueError, match="item must stay inside the configured root path"):
        connector.load(_file_record())
    assert client.byte_calls == []


def test_load_opaque_graph_item_id_downloads_its_content() -> None:
    item_id = "01BYE5RZ6QN3ZWBTUFOFD3GSPGOHDJD36K"
    client = FakeGraphClient()
    client.add(f"drives/drive1/items/{item_id}", file_item(item_id, "Guide.docx"))
    client.downloads[f"drives/drive1/items/{item_id}/content"] = b"docx-bytes"
    connector = _site_id_connector(client)

    document = connector.load(_file_record(item_id))

    assert document.content == b"docx-bytes"
    assert client.byte_calls == [f"drives/drive1/items/{item_id}/content"]


def test_load_by_ids_valid_ids_loads_each_item() -> None:
    """The item is fetched once to build its record and again to confirm it is still a file."""
    client = FakeGraphClient()
    add_site_and_default_drive(client)
    client.add(
        "drives/drive1/items/file1",
        file_item("file1", "A.docx"),
        file_item("file1", "A.docx"),
    )
    client.downloads["drives/drive1/items/file1/content"] = b"bytes-a"
    connector = SharePointConnector(config(), client=client)

    documents = list(connector.load_by_ids(["file1"]))

    assert [d.content for d in documents] == [b"bytes-a"]


@pytest.mark.parametrize("item_id", ["../../../sites/site2/drive/root", "folder1/..", "a?b"])
def test_load_by_ids_unsafe_item_id_raises_before_item_request(item_id: str) -> None:
    client = FakeGraphClient()
    add_site_and_default_drive(client)
    connector = SharePointConnector(config(), client=client)

    with pytest.raises(ValueError, match="drive item ID"):
        list(connector.load_by_ids([item_id]))
    assert not any("/items/" in endpoint for endpoint, _ in client.calls)
    assert client.byte_calls == []


def test_load_by_ids_item_inside_root_path_loads_it() -> None:
    client = FakeGraphClient()
    add_site_and_default_drive(client)
    client.add(
        "drives/drive1/items/file1",
        file_item("file1", "A.docx"),
        file_item("file1", "A.docx"),
    )
    client.downloads["drives/drive1/items/file1/content"] = b"bytes-a"
    connector = SharePointConnector(config(root_path="Docs"), client=client)

    documents = list(connector.load_by_ids(["file1"]))

    assert [d.content for d in documents] == [b"bytes-a"]


def test_load_by_ids_item_outside_root_path_raises_before_download() -> None:
    item = file_item("file1", "A.docx")
    item["parentReference"]["path"] = "/drive/root:/Secrets"
    client = FakeGraphClient()
    add_site_and_default_drive(client)
    client.add("drives/drive1/items/file1", item)
    client.downloads["drives/drive1/items/file1/content"] = b"bytes-a"
    connector = SharePointConnector(config(root_path="Docs"), client=client)

    with pytest.raises(ValueError, match="item must stay inside the configured root path"):
        list(connector.load_by_ids(["file1"]))
    assert client.byte_calls == []


def test_load_by_ids_without_root_path_loads_item_from_any_folder() -> None:
    item = file_item("file1", "A.docx")
    item["parentReference"]["path"] = "/drive/root:/Secrets"
    client = FakeGraphClient()
    add_site_and_default_drive(client)
    client.add("drives/drive1/items/file1", item, item)
    client.downloads["drives/drive1/items/file1/content"] = b"bytes-a"
    connector = SharePointConnector(config(), client=client)

    documents = list(connector.load_by_ids(["file1"]))

    assert [d.content for d in documents] == [b"bytes-a"]
