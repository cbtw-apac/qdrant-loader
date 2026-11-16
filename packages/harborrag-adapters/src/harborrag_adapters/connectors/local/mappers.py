"""Mappings from local files to Harbor domain objects."""

from __future__ import annotations

import os
from pathlib import Path

from harborrag_core.domain.source import SourceRecord

from .filesystem_paths import (
    guess_mime_type,
    relative_path,
    stat_datetime,
)
from .schemas import LocalFileMetadata


def file_created_timestamp(stat: os.stat_result) -> float:
    """Return the file creation timestamp exposed by the local OS.

    Windows exposes ``st_birthtime`` for the file's creation time, while many
    POSIX platforms only expose ``st_ctime`` and use it as the closest available
    metadata timestamp. The caller still interprets this as "created" rather than
    "last metadata-changed".
    """
    return getattr(stat, "st_birthtime", stat.st_ctime)


def path_from_record(record: SourceRecord) -> Path:
    """Recover the filesystem path from a local source record."""
    path = record.metadata.get("path") or record.locator
    if not path:
        raise ValueError(f"SourceRecord {record.id!r} does not contain path")
    return Path(str(path))


def build_source_record(
    path: Path,
    *,
    root_path: Path,
    checksum: str | None,
    is_symlink: bool,
) -> SourceRecord:
    """Convert a local file path into a lightweight source record.

    ``is_symlink`` must be captured by the caller before ``path`` is resolved —
    traversal resolves symlinks to their real target, so ``path.is_symlink()``
    here would always be ``False``.
    """
    stat = path.stat()
    relative = relative_path(path, root_path)
    mime_type = guess_mime_type(path)

    created_at = stat_datetime(file_created_timestamp(stat))
    updated_at = stat_datetime(stat.st_mtime)

    return SourceRecord(
        id=relative,
        source_type=mime_type,
        locator=relative,
        updated_at=updated_at,
        checksum=checksum,
        metadata={
            "source_system": "local",
            "relative_path": relative,
            "name": path.name,
            "parent_relative_path": Path(relative).parent.as_posix(),
            "suffix": path.suffix.lower(),
            "size": stat.st_size,
            "created_at": created_at,
            "updated_at": updated_at,
            "accessed_at": stat_datetime(stat.st_atime),
            "is_symlink": is_symlink,
        },
    )


def build_document_metadata(
    path: Path,
    *,
    root_path: Path,
    checksum: str,
    is_symlink: bool,
    stat_result: os.stat_result | None = None,
) -> LocalFileMetadata:
    """Build parsed provenance metadata for a loaded local file.

    ``is_symlink`` must be captured by the caller before ``path`` is resolved;
    see :func:`build_source_record`.
    """
    stat = stat_result or path.stat()
    relative = relative_path(path, root_path)
    return LocalFileMetadata(
        record_id=relative,
        title=path.name,
        checksum=checksum,
        created_at=stat_datetime(file_created_timestamp(stat)),
        updated_at=stat_datetime(stat.st_mtime),
        relative_path=relative,
        name=path.name,
        parent_relative_path=Path(relative).parent.as_posix(),
        suffix=path.suffix.lower(),
        size=stat.st_size,
        accessed_at=stat_datetime(stat.st_atime),
        is_symlink=is_symlink,
    )
