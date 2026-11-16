"""Unit tests for SharePoint connector discovery."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from sharepoint_test_helpers import (
    FakeGraphClient,
    add_site_and_default_drive,
    config,
    drive,
    file_item,
    folder_item,
    site,
)

from harborrag_adapters.connectors import SharePointConnector
from harborrag_adapters.connectors.schemas import ConnectorQuery

pytestmark = [pytest.mark.unit, pytest.mark.graybox]

_OTHER_SITE_LIBRARY = "../../../sites/site2/drive/root"
_UNSAFE_ITEM_IDS = (_OTHER_SITE_LIBRARY, "folder1/..", "..", "a?b", "a:b", "a%2Fb")


def _requested_item_endpoints(client: FakeGraphClient) -> list[str]:
    return [endpoint for endpoint, _ in client.calls if "/items/" in endpoint]


def _in_folder(item: dict[str, Any], parent_path: str | None) -> dict[str, Any]:
    reference: dict[str, Any] = {"driveId": "drive1", "id": "parent"}
    if parent_path is not None:
        reference["path"] = parent_path
    item["parentReference"] = reference
    return item


def _records_before_error(connector: SharePointConnector, query: ConnectorQuery) -> list[str]:
    records: list[str] = []
    with pytest.raises(ValueError, match="item must stay inside the configured root path"):
        for record in connector.discover(query):
            records.append(record.id)
    return records


def test_discover_root_path_with_subfolders_yields_matching_files() -> None:
    client = FakeGraphClient()
    add_site_and_default_drive(client)
    client.add(
        "drives/drive1/root:/Docs:/children",
        {
            "value": [
                folder_item(),
                file_item("file1", "Guide.docx"),
                file_item("skip", "Draft.txt"),
            ],
            "@odata.nextLink": "https://graph.microsoft.com/v1.0/page2",
        },
    )
    client.add(
        "https://graph.microsoft.com/v1.0/page2",
        {"value": [file_item("hidden", "Hidden.docx", hidden=True)]},
    )
    client.add(
        "drives/drive1/items/folder1/children",
        {"value": [file_item("file2", "Nested.pdf", parent_id="folder1")]},
    )
    connector = SharePointConnector(
        config(root_path="Docs", allowed_extensions={".docx", ".pdf"}),
        client=client,
    )

    records = list(
        connector.discover(
            ConnectorQuery(
                updated_after=datetime(2024, 1, 1, tzinfo=UTC),
                pattern="*d*",
            )
        )
    )

    assert [record.metadata["item_id"] for record in records] == ["file1", "file2"]
    assert records[0].id == "sharepoint://site1/drive1/file1"
    assert records[0].source_type.endswith("wordprocessingml.document")
    assert records[0].checksum == "hash-file1"
    assert ("https://graph.microsoft.com/v1.0/page2", None) in client.calls


def test_discover_item_ids_on_named_drive_yields_items() -> None:
    client = FakeGraphClient()
    client.add("sites/contoso.sharepoint.com:/sites/Engineering", site())
    client.add(
        "sites/site1/drives",
        {"value": [drive("drive0", "Assets"), drive("drive1", "Documents")]},
    )
    client.add("drives/drive1/items/file1", file_item("file1", "Guide.docx"))
    connector = SharePointConnector(config(drive_name="Documents"), client=client)

    records = list(connector.discover(ConnectorQuery(filters={"item_ids": ["file1"]})))

    assert records[0].locator == "file1"
    assert records[0].metadata["drive_id"] == "drive1"


def test_discover_limit_during_item_ids_stops_early() -> None:
    client = FakeGraphClient()
    add_site_and_default_drive(client)
    client.add("drives/drive1/items/file1", file_item("file1", "A.docx"))
    client.add("drives/drive1/items/file2", file_item("file2", "B.docx"))
    connector = SharePointConnector(config(), client=client)

    records = list(
        connector.discover(ConnectorQuery(limit=1, filters={"item_ids": ["file1", "file2"]}))
    )

    assert [r.metadata["item_id"] for r in records] == ["file1"]


def test_discover_limit_during_folder_walk_stops_early() -> None:
    client = FakeGraphClient()
    add_site_and_default_drive(client)
    client.add(
        "drives/drive1/root/children",
        {"value": [file_item("file1", "A.docx"), file_item("file2", "B.docx")]},
    )
    connector = SharePointConnector(config(), client=client)

    records = list(connector.discover(ConnectorQuery(limit=1)))

    assert [r.metadata["item_id"] for r in records] == ["file1"]


def test_discover_item_ids_bare_string_yields_item() -> None:
    client = FakeGraphClient()
    add_site_and_default_drive(client)
    client.add("drives/drive1/items/file1", file_item("file1", "A.docx"))
    connector = SharePointConnector(config(), client=client)

    records = list(connector.discover(ConnectorQuery(filters={"item_ids": "file1"})))
    assert [r.metadata["item_id"] for r in records] == ["file1"]


def test_discover_drive_item_ids_alias_yields_items() -> None:
    client = FakeGraphClient()
    add_site_and_default_drive(client)
    client.add("drives/drive1/items/file1", file_item("file1", "A.docx"))
    connector = SharePointConnector(config(), client=client)

    records = list(connector.discover(ConnectorQuery(filters={"drive_item_ids": ["file1"]})))
    assert [r.metadata["item_id"] for r in records] == ["file1"]


def test_discover_folder_item_id_alias_walks_folder() -> None:
    client = FakeGraphClient()
    add_site_and_default_drive(client)
    client.add(
        "drives/drive1/items/folder1/children",
        {"value": [file_item("file1", "A.docx", parent_id="folder1")]},
    )
    connector = SharePointConnector(config(), client=client)

    records = list(connector.discover(ConnectorQuery(filters={"folder_item_id": "folder1"})))
    assert [r.metadata["item_id"] for r in records] == ["file1"]


@pytest.mark.parametrize("filter_key", ["item_ids", "drive_item_ids", "file_ids"])
@pytest.mark.parametrize("item_id", _UNSAFE_ITEM_IDS)
def test_discover_unsafe_item_id_filter_raises_before_item_request(
    filter_key: str, item_id: str
) -> None:
    client = FakeGraphClient()
    add_site_and_default_drive(client)
    connector = SharePointConnector(config(), client=client)

    with pytest.raises(ValueError, match="drive item ID"):
        list(connector.discover(ConnectorQuery(filters={filter_key: [item_id]})))

    assert _requested_item_endpoints(client) == []


@pytest.mark.parametrize("filter_key", ["root_item_id", "folder_item_id"])
@pytest.mark.parametrize("item_id", _UNSAFE_ITEM_IDS)
def test_discover_unsafe_root_item_id_filter_raises_before_children_request(
    filter_key: str, item_id: str
) -> None:
    client = FakeGraphClient()
    add_site_and_default_drive(client)
    connector = SharePointConnector(config(), client=client)

    with pytest.raises(ValueError, match="drive item ID"):
        list(connector.discover(ConnectorQuery(filters={filter_key: item_id})))

    assert _requested_item_endpoints(client) == []


@pytest.mark.parametrize("item_id", ["01BYE5RZ6QN3ZWBTUFOFD3GSPGOHDJD36K", "ABC!123", "root"])
def test_discover_opaque_graph_item_id_filter_yields_item(item_id: str) -> None:
    client = FakeGraphClient()
    add_site_and_default_drive(client)
    client.add(f"drives/drive1/items/{item_id}", file_item(item_id, "A.docx"))
    connector = SharePointConnector(config(), client=client)

    records = list(connector.discover(ConnectorQuery(filters={"item_ids": [item_id]})))

    assert [r.metadata["item_id"] for r in records] == [item_id]


@pytest.mark.parametrize("path", ["..", "Docs/..", "Docs/../../Other", "./Docs", "Docs//HR"])
def test_discover_query_path_with_dot_or_empty_segments_raises_before_listing(path: str) -> None:
    client = FakeGraphClient()
    add_site_and_default_drive(client)
    connector = SharePointConnector(config(root_path="Docs"), client=client)

    with pytest.raises(ValueError, match=r"must not contain empty, '\.' or '\.\.' segments"):
        list(connector.discover(ConnectorQuery(path=path)))

    assert not any("children" in endpoint for endpoint, _ in client.calls)


@pytest.mark.parametrize("path", ["Other", "Doc", "Docs2", "Archive/Docs"])
def test_discover_query_path_outside_root_path_raises_before_listing(path: str) -> None:
    client = FakeGraphClient()
    add_site_and_default_drive(client)
    connector = SharePointConnector(config(root_path="Docs"), client=client)

    with pytest.raises(ValueError, match="must stay inside the configured root path"):
        list(connector.discover(ConnectorQuery(path=path)))

    assert not any("children" in endpoint for endpoint, _ in client.calls)


@pytest.mark.parametrize("path", ["/", ""])
def test_discover_empty_query_path_walks_configured_root_path(path: str) -> None:
    client = FakeGraphClient()
    add_site_and_default_drive(client)
    client.add("drives/drive1/root:/Docs:/children", {"value": [file_item("file1", "A.docx")]})
    connector = SharePointConnector(config(root_path="Docs"), client=client)

    records = list(connector.discover(ConnectorQuery(path=path)))

    assert [r.metadata["item_id"] for r in records] == ["file1"]


@pytest.mark.parametrize("path", ["Docs", "/Docs/HR/", "docs/HR"])
def test_discover_query_path_inside_root_path_walks_that_folder(path: str) -> None:
    client = FakeGraphClient()
    add_site_and_default_drive(client)
    folder = path.strip("/")
    client.add(f"drives/drive1/root:/{folder}:/children", {"value": [file_item("file1", "A.docx")]})
    connector = SharePointConnector(config(root_path="Docs"), client=client)

    records = list(connector.discover(ConnectorQuery(path=path)))

    assert [r.metadata["item_id"] for r in records] == ["file1"]


def test_discover_query_path_without_root_path_walks_that_folder() -> None:
    client = FakeGraphClient()
    add_site_and_default_drive(client)
    client.add("drives/drive1/root:/Other:/children", {"value": [file_item("file1", "A.docx")]})
    connector = SharePointConnector(config(), client=client)

    records = list(connector.discover(ConnectorQuery(path="Other")))

    assert [r.metadata["item_id"] for r in records] == ["file1"]


@pytest.mark.parametrize("filter_key", ["item_ids", "drive_item_ids", "file_ids"])
def test_discover_item_id_inside_root_path_yields_item(filter_key: str) -> None:
    client = FakeGraphClient()
    add_site_and_default_drive(client)
    client.add("drives/drive1/items/file1", file_item("file1", "A.docx"))
    connector = SharePointConnector(config(root_path="Docs"), client=client)

    records = list(connector.discover(ConnectorQuery(filters={filter_key: ["file1"]})))

    assert [r.metadata["item_id"] for r in records] == ["file1"]


def test_discover_item_id_in_percent_encoded_root_path_yields_item() -> None:
    client = FakeGraphClient()
    add_site_and_default_drive(client)
    item = _in_folder(file_item("file1", "A.docx"), "/drive/root:/Docs%20Archive/2024")
    client.add("drives/drive1/items/file1", item)
    connector = SharePointConnector(config(root_path="docs archive"), client=client)

    records = list(connector.discover(ConnectorQuery(filters={"item_ids": ["file1"]})))

    assert [r.metadata["item_id"] for r in records] == ["file1"]


@pytest.mark.parametrize(
    "item",
    [
        _in_folder(file_item("file1", "A.docx"), "/drive/root:/Secrets"),
        _in_folder(file_item("file1", "A.docx"), "/drive/root:/Docs2"),
        _in_folder(file_item("file1", "A.docx"), "/drive/root:"),
        _in_folder(file_item("file1", "A.docx"), None),
        _in_folder(folder_item("file1", "Docs"), None),
        _in_folder(folder_item("file1", "Runbooks"), "/drive/root:"),
    ],
    ids=[
        "other-folder",
        "sibling-prefix",
        "drive-root",
        "no-parent-path",
        "root-name-without-parent-path",
        "folder",
    ],
)
def test_discover_item_id_outside_root_path_raises_before_yielding(item: dict[str, Any]) -> None:
    client = FakeGraphClient()
    add_site_and_default_drive(client)
    client.add("drives/drive1/items/file1", item)
    connector = SharePointConnector(config(root_path="Docs"), client=client)

    records = _records_before_error(connector, ConnectorQuery(filters={"item_ids": ["file1"]}))

    assert records == []
    assert not any("children" in endpoint for endpoint, _ in client.calls)


def test_discover_item_id_without_root_path_yields_item_from_any_folder() -> None:
    client = FakeGraphClient()
    add_site_and_default_drive(client)
    client.add(
        "drives/drive1/items/file1",
        _in_folder(file_item("file1", "A.docx"), "/drive/root:/Secrets"),
    )
    connector = SharePointConnector(config(), client=client)

    records = list(connector.discover(ConnectorQuery(filters={"item_ids": ["file1"]})))

    assert [r.metadata["item_id"] for r in records] == ["file1"]


@pytest.mark.parametrize("filter_key", ["root_item_id", "folder_item_id"])
@pytest.mark.parametrize(
    "folder",
    [
        _in_folder(folder_item("folder1", "HR"), "/drive/root:/Docs"),
        _in_folder(folder_item("folder1", "Docs"), "/drive/root:"),
    ],
    ids=["below-root", "root-itself"],
)
def test_discover_folder_item_id_inside_root_path_walks_folder(
    filter_key: str, folder: dict[str, Any]
) -> None:
    client = FakeGraphClient()
    add_site_and_default_drive(client)
    client.add("drives/drive1/items/folder1", folder)
    client.add(
        "drives/drive1/items/folder1/children",
        {"value": [file_item("file1", "A.docx", parent_id="folder1")]},
    )
    connector = SharePointConnector(config(root_path="Docs"), client=client)

    records = list(connector.discover(ConnectorQuery(filters={filter_key: "folder1"})))

    assert [r.metadata["item_id"] for r in records] == ["file1"]


@pytest.mark.parametrize("filter_key", ["root_item_id", "folder_item_id"])
def test_discover_folder_item_id_outside_root_path_raises_before_listing(filter_key: str) -> None:
    client = FakeGraphClient()
    add_site_and_default_drive(client)
    client.add("drives/drive1/items/folder1", folder_item("folder1", "Runbooks"))
    connector = SharePointConnector(config(root_path="Docs"), client=client)

    records = _records_before_error(connector, ConnectorQuery(filters={filter_key: "folder1"}))

    assert records == []
    assert not any("children" in endpoint for endpoint, _ in client.calls)


def test_discover_folder_item_id_without_root_path_lists_folder_without_item_lookup() -> None:
    client = FakeGraphClient()
    add_site_and_default_drive(client)
    client.add(
        "drives/drive1/items/folder1/children",
        {"value": [file_item("file1", "A.docx", parent_id="folder1")]},
    )
    connector = SharePointConnector(config(), client=client)

    records = list(connector.discover(ConnectorQuery(filters={"root_item_id": "folder1"})))

    assert [r.metadata["item_id"] for r in records] == ["file1"]
    assert "drives/drive1/items/folder1" not in [endpoint for endpoint, _ in client.calls]
