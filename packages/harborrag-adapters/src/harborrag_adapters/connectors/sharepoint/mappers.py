"""Mappings from Microsoft Graph payloads to Harbor domain objects."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from harborrag_core.domain.source import SourceRecord

from .drive_paths import item_mime_type, item_name, item_path
from .schemas import SharePointMetadata, SharePointPageMetadata, SharePointParentReference

PAGE_RECORD_KIND = "page"


def parse_timestamp(value: str | None) -> datetime | None:
    """Parse a Microsoft Graph timestamp into a UTC datetime.

    Graph sends ISO 8601 UTC (``...Z``); an offset or a naive value is still
    normalized to UTC so stored timestamps always serialize as ISO 8601 UTC.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def drive_item_id_from_record(record: SourceRecord) -> str:
    """Recover the Graph drive item ID from a source record.

    An ID in ``metadata["item_id"]`` is returned whole, so a malformed one
    fails the endpoint builder's check instead of loading the item its last
    segment names. Only a record without it falls back to the last segment of
    its locator.

    Args:
        record: File record from discovery or built by a caller.

    Returns:
        The drive item ID, not yet checked as a URL path segment.

    Raises:
        ValueError: The record has neither ``metadata["item_id"]`` nor a locator.
    """
    return _graph_id_from_record(record, "item_id")


def is_page_record(record: SourceRecord) -> bool:
    """Return whether a source record points at a site page rather than a file."""
    if record.metadata.get("record_kind") == PAGE_RECORD_KIND:
        return True
    return record.id.startswith("sharepoint://") and "/pages/" in record.id


def page_id_from_record(record: SourceRecord) -> str:
    """Recover the Graph site page ID from a page source record.

    An ID in ``metadata["page_id"]`` is returned whole, like the item ID of
    ``drive_item_id_from_record``; only a record without it falls back to the
    last segment of its locator.

    Args:
        record: Page record from discovery or built by a caller.

    Returns:
        The site page ID, not yet checked as a URL path segment.

    Raises:
        ValueError: The record has neither ``metadata["page_id"]`` nor a locator.
    """
    return _graph_id_from_record(record, "page_id")


def _graph_id_from_record(record: SourceRecord, metadata_key: str) -> str:
    """Return the record's explicit Graph ID whole, else the last segment of its locator.

    Args:
        record: Source record to read.
        metadata_key: Metadata key that holds the explicit ID.

    Raises:
        ValueError: The record has neither the metadata ID nor a locator.
    """
    explicit_id = record.metadata.get(metadata_key)
    if explicit_id:
        return str(explicit_id)
    if not record.locator:
        raise ValueError(f"SourceRecord {record.id!r} does not contain {metadata_key}")
    return str(record.locator).rstrip("/").rsplit("/", 1)[-1]


def build_page_source_record(page: dict[str, Any], *, site_id: str) -> SourceRecord:
    """Convert a Microsoft Graph site page into a source record.

    Page IDs live under a literal ``pages`` segment where file records carry a
    drive ID, so the two kinds of record can never share an identity.
    """
    page_id = str(page.get("id") or "")
    publishing = page.get("publishingState")
    publishing = publishing if isinstance(publishing, dict) else {}
    return SourceRecord(
        id=f"sharepoint://{site_id}/pages/{page_id}",
        source_type="text/html",
        locator=page_id,
        updated_at=parse_timestamp(page.get("lastModifiedDateTime")),
        checksum=page.get("eTag"),
        metadata={
            "source_system": "sharepoint",
            "record_kind": PAGE_RECORD_KIND,
            "site_id": site_id,
            "page_id": page_id,
            "name": str(page.get("name") or ""),
            "title": str(page.get("title") or page.get("name") or ""),
            "page_layout": page.get("pageLayout"),
            "publishing_level": publishing.get("level"),
            "publishing_version": publishing.get("versionId"),
            "etag": page.get("eTag"),
            "created_at": parse_timestamp(page.get("createdDateTime")),
            "author": _identity_name(page.get("createdBy")),
            "created_by": _identity_name(page.get("createdBy")),
            "updated_by": _identity_name(page.get("lastModifiedBy")),
        },
    )


def build_page_document_metadata(
    page: dict[str, Any],
    *,
    site: dict[str, Any],
    title: str,
    checksum: str,
    has_text_content: bool,
) -> SharePointPageMetadata:
    """Build parsed provenance metadata for a loaded SharePoint site page."""
    page_id = str(page.get("id") or "")
    return SharePointPageMetadata(
        record_id=page_id,
        title=title,
        checksum=checksum,
        created_at=parse_timestamp(page.get("createdDateTime")),
        updated_at=parse_timestamp(page.get("lastModifiedDateTime")),
        site_id=site.get("id"),
        site_name=site.get("name") or site.get("displayName"),
        page_id=page_id,
        item_name=str(page.get("name") or ""),
        page_layout=page.get("pageLayout"),
        etag=page.get("eTag"),
        author=_identity_name(page.get("createdBy")),
        created_by=_identity_name(page.get("createdBy")),
        updated_by=_identity_name(page.get("lastModifiedBy")),
        has_text_content=has_text_content,
    )


def build_source_record(
    item: dict[str, Any],
    *,
    site_id: str,
    drive_id: str,
) -> SourceRecord:
    """Convert a Microsoft Graph drive item into a source record."""
    item_id = str(item.get("id") or "")
    mime_type = item_mime_type(item)
    path = item_path(item)
    checksum = _item_checksum(item)

    return SourceRecord(
        id=f"sharepoint://{site_id}/{drive_id}/{item_id}",
        source_type=mime_type,
        locator=item_id,
        updated_at=parse_timestamp(item.get("lastModifiedDateTime")),
        checksum=checksum,
        metadata={
            "source_system": "sharepoint",
            "site_id": site_id,
            "drive_id": drive_id,
            "item_id": item_id,
            "name": item_name(item),
            "path": path,
            "size": int(item.get("size") or 0),
            "etag": item.get("eTag"),
            "ctag": item.get("cTag"),
            "created_at": parse_timestamp(item.get("createdDateTime")),
            "author": _identity_name(item.get("createdBy")),
            "created_by": _identity_name(item.get("createdBy")),
            "updated_by": _identity_name(item.get("lastModifiedBy")),
            "parent_id": item.get("parentReference", {}).get("id"),
            "parent_path": item.get("parentReference", {}).get("path"),
        },
    )


def build_document_metadata(
    item: dict[str, Any],
    *,
    site: dict[str, Any],
    drive: dict[str, Any],
    checksum: str,
) -> SharePointMetadata:
    """Build parsed provenance metadata for a loaded SharePoint file."""
    parent = item.get("parentReference", {})
    item_id = str(item.get("id") or "")
    title = item_name(item)
    return SharePointMetadata(
        record_id=item_id,
        title=title,
        checksum=checksum,
        created_at=parse_timestamp(item.get("createdDateTime")),
        updated_at=parse_timestamp(item.get("lastModifiedDateTime")),
        site_id=site.get("id"),
        site_name=site.get("name") or site.get("displayName"),
        drive_id=drive.get("id"),
        drive_name=drive.get("name"),
        drive_type=drive.get("driveType"),
        item_id=item_id,
        item_name=title,
        path=item_path(item),
        size=int(item.get("size") or 0),
        etag=item.get("eTag"),
        ctag=item.get("cTag"),
        author=_identity_name(item.get("createdBy")),
        created_by=_identity_name(item.get("createdBy")),
        updated_by=_identity_name(item.get("lastModifiedBy")),
        parent=SharePointParentReference(
            drive_id=parent.get("driveId"),
            id=parent.get("id"),
            path=parent.get("path"),
        ),
        sharepoint_hashes=_hashes(item),
    )


def _item_checksum(item: dict[str, Any]) -> str | None:
    hashes = _hashes(item)
    return (
        hashes.get("quickXorHash")
        or hashes.get("sha1Hash")
        or hashes.get("sha256Hash")
        or item.get("eTag")
        or item.get("cTag")
    )


def _hashes(item: dict[str, Any]) -> dict[str, Any]:
    file_info = item.get("file")
    if not isinstance(file_info, dict):
        return {}
    hashes = file_info.get("hashes")
    return hashes if isinstance(hashes, dict) else {}


def _identity_name(identity_set: Any) -> str | None:
    """Return a display name from a Graph identitySet, preferring the user.

    An identitySet can also name the ``application`` or ``device`` that acted;
    those are only used when no user identity is present.
    """
    if not isinstance(identity_set, dict):
        return None
    preferred = identity_set.get("user")
    candidates = [preferred, *(v for k, v in identity_set.items() if k != "user")]
    for value in candidates:
        if isinstance(value, dict):
            display_name = value.get("displayName") or value.get("email")
            if display_name:
                return str(display_name)
    return None
