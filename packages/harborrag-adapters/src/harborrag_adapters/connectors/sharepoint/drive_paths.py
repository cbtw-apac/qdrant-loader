"""Pure path, URL and payload helpers for SharePoint drives and site pages.

No I/O and no Graph client. ``validate_graph_id_segment`` is the one check for
a Graph ID spliced into a URL path: every drive-item endpoint is built here
through ``drive_item_endpoint``, and the site page endpoint applies it too, so
an ID from the caller or a stored record stays inside one URL path segment.
Payload readers take a raw Graph item ``dict`` and only read it.

Start from: drive_item_endpoint, validate_graph_id_segment, item_path.
"""

from __future__ import annotations

import re
from fnmatch import fnmatch
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote, unquote, urlparse

DRIVE_ITEM_SELECT = ",".join(
    (
        "id",
        "name",
        "webUrl",
        "size",
        "file",
        "folder",
        "package",
        "hidden",
        "parentReference",
        "createdDateTime",
        "lastModifiedDateTime",
        "createdBy",
        "lastModifiedBy",
        "eTag",
        "cTag",
    )
)
"""Drive item fields to request.

``@microsoft.graph.downloadUrl`` is deliberately absent: it is a pre-authenticated
link that bypasses SharePoint permissions for about an hour, and content is
downloaded through ``/content`` with the connector's own token instead.
"""

DRIVE_SELECT = "id,name,driveType,webUrl,createdDateTime,lastModifiedDateTime"

_GRAPH_ANNOTATION_PREFIX = "@microsoft.graph."
_GRAPH_ID_SEGMENT = re.compile(r"[A-Za-z0-9!_-]+")
_UNSAFE_GRAPH_ID = "{label} must be one URL path segment of letters, digits, '!', '_' or '-'"
_DRIVE_ITEM_ID_LABEL = "SharePoint drive item ID"
_DRIVE_ROOT_MARKER = "root:"


def stored_payload(item: dict[str, Any]) -> dict[str, Any]:
    """Return a Graph item without its ``@microsoft.graph.*`` annotations.

    The payload becomes ``RawDocument.raw`` and is written into the immutable
    raw-metadata artifact, so an annotation such as ``downloadUrl`` -- a
    credential-equivalent link -- must not travel with it even when an endpoint
    returns it unrequested.
    """
    return {
        key: value
        for key, value in item.items()
        if not str(key).startswith(_GRAPH_ANNOTATION_PREFIX)
    }


def parse_sharepoint_site_url(site_url: str) -> tuple[str, str]:
    """Parse a SharePoint site URL into its Graph hostname and site path.

    Args:
        site_url: Absolute ``http`` or ``https`` URL of the site.

    Returns:
        The hostname and the decoded site path without surrounding slashes.

    Raises:
        ValueError: ``site_url`` has no ``http``/``https`` scheme or no hostname.
    """
    parsed = urlparse(site_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("site_url must be an absolute SharePoint URL")

    path = unquote(parsed.path).strip("/")
    return parsed.hostname, path


def site_path_endpoint(hostname: str, site_path: str | None) -> str:
    """Build the Graph endpoint that resolves a SharePoint site by path."""
    path = (site_path or "").strip("/")
    if not path:
        return f"sites/{hostname}:/"
    return f"sites/{hostname}:/{path}"


def validate_graph_id_segment(value: str, *, label: str) -> str:
    """Return a Graph ID that is safe to put in one Graph URL path segment.

    Drive item and site page IDs are opaque tokens such as
    ``01BYE5RZ6QN3ZWBTUFOFD3GSPGOHDJD36K``, ``D4648F06C91D9D3D!54927``, a GUID
    or the alias ``root``. An ID can come from the caller (query filters,
    config ``item_ids``, ``load_by_ids``) or a stored record, and an HTTP client
    collapses ``..`` segments before sending, so an unchecked ID such as
    ``../../../sites/<site>/drive/root`` would reach another site.

    Args:
        value: ID to splice into the URL path.
        label: What the ID names, such as ``SharePoint site page ID``; it
            starts the error message.

    Returns:
        ``value`` unchanged.

    Raises:
        ValueError: ``value`` is empty or has a character other than an ASCII
            letter, digit, ``!``, ``_`` or ``-``. The message leaves the value out.
    """
    if not _GRAPH_ID_SEGMENT.fullmatch(value):
        raise ValueError(_UNSAFE_GRAPH_ID.format(label=label))
    return value


def drive_item_endpoint(drive_id: str, item_id: str) -> str:
    """Build the Graph endpoint of one item in a drive.

    Every ``drives/{drive_id}/items/{item_id}`` URL, with or without a
    ``/children`` or ``/content`` suffix, starts from this endpoint. The
    ``ValueError`` from ``validate_graph_id_segment`` passes through for an
    unsafe ``item_id``.

    Args:
        drive_id: Graph drive ID of the configured library.
        item_id: Drive item ID from Graph, config or the caller.

    Returns:
        The endpoint relative to the Graph API root.
    """
    segment = validate_graph_id_segment(item_id, label=_DRIVE_ITEM_ID_LABEL)
    return f"drives/{drive_id}/items/{segment}"


def children_endpoint(
    drive_id: str,
    *,
    item_id: str | None = None,
    path: str | None = None,
) -> str:
    """Build the Graph children endpoint for a folder item, a folder path or the drive root.

    The ``ValueError`` from ``validate_graph_id_segment`` passes through for
    an unsafe ``item_id``.

    Args:
        drive_id: Graph drive ID of the configured library.
        item_id: Folder item ID; takes precedence over ``path`` when set.
        path: Drive-relative folder path, already validated; empty or ``None``
            means the drive root.

    Returns:
        The endpoint relative to the Graph API root.
    """
    if item_id:
        return f"{drive_item_endpoint(drive_id, item_id)}/children"
    normalized_path = normalize_drive_path(path)
    if normalized_path:
        encoded_path = quote(normalized_path, safe="/")
        return f"drives/{drive_id}/root:/{encoded_path}:/children"
    return f"drives/{drive_id}/root/children"


def normalize_drive_path(path: str | None) -> str:
    """Normalize SharePoint drive paths to Graph's POSIX-like path style."""
    if not path:
        return ""
    normalized = path.strip("/")
    return str(PurePosixPath(normalized)) if normalized else ""


def is_within_drive_path(path: str, root_path: str | None) -> bool:
    """Return whether a drive path is ``root_path`` itself or lies below it.

    Segments are compared whole and case-insensitively, as SharePoint resolves
    paths, so ``Docs2`` is not inside ``Docs``. Both paths are expected to be
    validated already, without ``.`` or ``..`` segments.

    Args:
        path: Drive-relative path to check.
        root_path: Drive-relative root; empty or ``None`` is the drive root,
            which holds every path.

    Returns:
        Whether ``path`` stays inside ``root_path``.
    """
    root = normalize_drive_path(root_path).casefold()
    candidate = normalize_drive_path(path).casefold()
    return not root or candidate == root or candidate.startswith(f"{root}/")


def is_drive_file(item: dict[str, Any]) -> bool:
    """Return whether a Graph drive item is a downloadable file."""
    return isinstance(item.get("file"), dict)


def is_drive_folder(item: dict[str, Any]) -> bool:
    """Return whether a Graph drive item can contain children."""
    return isinstance(item.get("folder"), dict) or isinstance(item.get("package"), dict)


def item_name(item: dict[str, Any]) -> str:
    """Return the display name of a Graph drive item."""
    return str(item.get("name") or "")


def item_extension(item: dict[str, Any]) -> str:
    """Return the lowercased file extension for a drive item."""
    name = item_name(item)
    if "." not in name:
        return ""
    return PurePosixPath(name).suffix.lower()


def item_mime_type(item: dict[str, Any]) -> str:
    """Return a MIME type for a Graph drive item."""
    file_info = item.get("file")
    if isinstance(file_info, dict):
        return str(file_info.get("mimeType") or "application/octet-stream")
    if is_drive_folder(item):
        return "application/vnd.microsoft.graph.folder"
    return "application/octet-stream"


def item_hidden(item: dict[str, Any]) -> bool:
    """Return whether Graph marks a drive item as hidden."""
    value = item.get("hidden")
    return isinstance(value, dict) or value is True


def item_has_drive_location(item: dict[str, Any]) -> bool:
    """Return whether Graph ``parentReference`` metadata places an item in its drive.

    Graph gives a child of the drive root the parent path ``/drive/root:`` and
    a deeper item ``/drive/root:/<folders>``. Without that path ``item_path``
    falls back to the bare name, which says nothing about where the item sits.
    """
    return _DRIVE_ROOT_MARKER in _parent_path(item)


def item_path(item: dict[str, Any]) -> str:
    """Reconstruct a drive-relative path from Graph ``parentReference`` metadata.

    Graph percent-encodes ``itemReference.path`` (``root:/HR%20Policies``) while
    names, allowlist prefixes and ``root_path`` are plain text, so the folder
    part is decoded before the name is appended. An item without a drive
    location resolves to its bare name; see ``item_has_drive_location``.
    """
    name = item_name(item)
    parent_path = _parent_path(item)
    if _DRIVE_ROOT_MARKER not in parent_path:
        return name

    folder_path = unquote(parent_path.split(_DRIVE_ROOT_MARKER, 1)[1]).strip("/")
    if not folder_path:
        return name
    return f"{folder_path}/{name}".strip("/")


def _parent_path(item: dict[str, Any]) -> str:
    """Return the raw ``parentReference.path`` of a drive item, or ``""`` without one."""
    return str(item.get("parentReference", {}).get("path") or "")


def matches_pattern(item: dict[str, Any], pattern: str | None) -> bool:
    """Return whether a drive item name matches a query pattern."""
    if not pattern:
        return True
    name = item_name(item).lower()
    normalized = pattern.lower()
    if any(char in normalized for char in "*?[]"):
        return fnmatch(name, normalized)
    return normalized in name
