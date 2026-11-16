"""Unit tests for SharePoint connector URL/path/endpoint utility helpers."""

from __future__ import annotations

import pytest
from sharepoint_test_helpers import folder_item

from harborrag_adapters.connectors.sharepoint.drive_paths import (
    children_endpoint,
    drive_item_endpoint,
    is_within_drive_path,
    item_extension,
    item_mime_type,
    item_path,
    matches_pattern,
    parse_sharepoint_site_url,
    site_path_endpoint,
    validate_graph_id_segment,
)

pytestmark = [pytest.mark.unit, pytest.mark.whitebox]

_VALID_ITEM_IDS = (
    "root",
    "4e2b1d3a-8c7f-4b6e-9a1d-2f3c4b5a6d7e",
    "01BYE5RZ6QN3ZWBTUFOFD3GSPGOHDJD36K",
    "D4648F06C91D9D3D!54927",
    "ABC!123",
    "file1",
    "wp-6",
    "a_b",
)
_UNSAFE_ITEM_IDS = (
    "..",
    ".",
    "../../../sites/site2/drive/root",
    "folder1/..",
    "a/b",
    "a?b",
    "a:b",
    "a%2Fb",
    "a#b",
    "a b",
    "a.b",
    "file1\n",
)


def test_children_endpoint_root_path_or_item_returns_children_endpoint() -> None:
    assert children_endpoint("drive1") == "drives/drive1/root/children"
    assert (
        children_endpoint("drive1", path="Shared Documents")
        == "drives/drive1/root:/Shared%20Documents:/children"
    )
    assert children_endpoint("drive1", item_id="folder1") == "drives/drive1/items/folder1/children"


@pytest.mark.parametrize("item_id", _UNSAFE_ITEM_IDS)
def test_children_endpoint_unsafe_item_id_raises(item_id: str) -> None:
    with pytest.raises(ValueError, match="drive item ID"):
        children_endpoint("drive1", item_id=item_id)


@pytest.mark.parametrize("item_id", _VALID_ITEM_IDS)
def test_validate_graph_id_segment_valid_id_returns_it(item_id: str) -> None:
    assert validate_graph_id_segment(item_id, label="Test ID") == item_id


@pytest.mark.parametrize("item_id", ["", *_UNSAFE_ITEM_IDS])
def test_validate_graph_id_segment_unsafe_id_raises_with_label(item_id: str) -> None:
    with pytest.raises(ValueError, match="^Test ID must be one URL path segment"):
        validate_graph_id_segment(item_id, label="Test ID")


def test_validate_graph_id_segment_unsafe_id_keeps_value_out_of_message() -> None:
    with pytest.raises(ValueError, match="Test ID") as error:
        validate_graph_id_segment("../../../sites/other-site/drive/root", label="Test ID")

    assert "other-site" not in str(error.value)


@pytest.mark.parametrize("item_id", _VALID_ITEM_IDS)
def test_drive_item_endpoint_valid_id_returns_item_endpoint(item_id: str) -> None:
    assert drive_item_endpoint("drive1", item_id) == f"drives/drive1/items/{item_id}"


@pytest.mark.parametrize("item_id", ["", *_UNSAFE_ITEM_IDS])
def test_drive_item_endpoint_unsafe_id_raises(item_id: str) -> None:
    with pytest.raises(ValueError, match="drive item ID"):
        drive_item_endpoint("drive1", item_id)


@pytest.mark.parametrize(
    ("path", "root_path", "expected"),
    [
        ("Docs", "Docs", True),
        ("Docs/HR", "Docs", True),
        ("docs/hr", "Docs", True),
        ("Docs/HR/2024", "Docs/HR", True),
        ("Docs2", "Docs", False),
        ("Doc", "Docs", False),
        ("Other/Docs", "Docs", False),
        ("Docs", "Docs/HR", False),
        ("Anything", None, True),
        ("Anything", "", True),
    ],
)
def test_is_within_drive_path_compares_whole_segments_ignoring_case(
    path: str, root_path: str | None, expected: bool
) -> None:
    assert is_within_drive_path(path, root_path) is expected


def test_parse_sharepoint_site_url_relative_url_raises() -> None:
    with pytest.raises(ValueError, match="absolute SharePoint URL"):
        parse_sharepoint_site_url("not-a-url")


def test_site_path_endpoint_without_path_returns_site_root() -> None:
    assert site_path_endpoint("contoso.sharepoint.com", None) == ("sites/contoso.sharepoint.com:/")
    assert site_path_endpoint("contoso.sharepoint.com", "") == ("sites/contoso.sharepoint.com:/")


def test_item_extension_name_without_dot_returns_empty() -> None:
    assert item_extension({"name": "README"}) == ""


def test_item_mime_type_folder_or_unknown_returns_fallback() -> None:
    assert item_mime_type(folder_item()) == "application/vnd.microsoft.graph.folder"
    assert item_mime_type({"id": "x"}) == "application/octet-stream"


def test_item_path_without_root_marker_returns_name() -> None:
    item = {"name": "Doc.txt", "parentReference": {"path": "/drive/other"}}
    assert item_path(item) == "Doc.txt"


def test_item_path_with_empty_folder_path_returns_name() -> None:
    item = {"name": "Doc.txt", "parentReference": {"path": "/drive/root:"}}
    assert item_path(item) == "Doc.txt"


def test_matches_pattern_plain_substring_matches_case_insensitively() -> None:
    assert matches_pattern({"name": "Guide.docx"}, "guide") is True
    assert matches_pattern({"name": "Guide.docx"}, "missing") is False
