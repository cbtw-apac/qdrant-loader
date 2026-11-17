"""Whitebox unit tests for LocalFileSystem size/checksum/scope helpers."""

from __future__ import annotations

from pathlib import Path

import pytest
from local_test_helpers import config, write_file

from harborrag_adapters.connectors.exceptions import DocumentProcessingError
from harborrag_adapters.connectors.local.filesystem import LocalFileSystem
from harborrag_adapters.connectors.local.filesystem_paths import stat_datetime

pytestmark = [pytest.mark.unit, pytest.mark.whitebox]


def test_enforce_size_limit_noop_without_configured_limit(tmp_path: Path):
    path = write_file(tmp_path / "a.txt", b"hello")
    files = LocalFileSystem(config(tmp_path, max_file_size_bytes=None))
    files.enforce_size_limit(path, 10_000_000)


def test_read_capped_bytes_returns_content_within_limit(tmp_path: Path):
    path = write_file(tmp_path / "a.txt", b"hello")
    files = LocalFileSystem(config(tmp_path, max_file_size_bytes=10))
    assert files.read_capped_bytes(path) == b"hello"


def test_read_capped_bytes_ignores_limit_when_not_configured(tmp_path: Path):
    path = write_file(tmp_path / "a.txt", b"hello")
    files = LocalFileSystem(config(tmp_path, max_file_size_bytes=None))
    assert files.read_capped_bytes(path) == b"hello"


def test_read_capped_bytes_raises_when_content_exceeds_limit_during_read(
    tmp_path: Path,
):
    path = write_file(tmp_path / "big.txt", b"0123456789")
    files = LocalFileSystem(config(tmp_path, max_file_size_bytes=5))

    with pytest.raises(DocumentProcessingError, match="exceeds max_file_size_bytes"):
        files.read_capped_bytes(path)


def test_checksum_mode_none_returns_no_checksum(tmp_path: Path):
    path = write_file(tmp_path / "a.txt")
    files = LocalFileSystem(config(tmp_path, checksum_mode="none"))
    assert files.checksum(path) is None


def test_checksum_mode_sha256_matches_the_secure_descriptor_hash(tmp_path: Path):
    import hashlib

    path = write_file(tmp_path / "a.txt", b"hello world")
    files = LocalFileSystem(config(tmp_path, checksum_mode="sha256"))

    assert files.checksum(path) == hashlib.sha256(b"hello world").hexdigest()
    assert files.checksum(path) == files.read_snapshot(path).checksum


def test_checksum_mode_sha256_refuses_a_path_outside_source_scope(
    tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
):
    other_root = tmp_path_factory.mktemp("outside-scope")
    outside = write_file(other_root / "probe.txt", b"nope")

    files = LocalFileSystem(config(tmp_path, checksum_mode="sha256"))
    with pytest.raises(DocumentProcessingError, match="outside configured source scope"):
        files.checksum(outside)


def test_source_record_includes_created_and_updated_timestamps(tmp_path: Path):
    path = write_file(tmp_path / "a.txt", "hello")
    files = LocalFileSystem(config(tmp_path))

    record = files.source_record(path, is_symlink=False)
    stat = path.stat()
    created = getattr(stat, "st_birthtime", stat.st_ctime)

    assert record.metadata["created_at"] == stat_datetime(created)
    assert record.metadata["updated_at"] == stat_datetime(stat.st_mtime)


def test_within_source_scope_for_single_file_source(tmp_path: Path):
    path = write_file(tmp_path / "solo.md")
    files = LocalFileSystem(config(path))
    assert files.within_source_scope(path.resolve()) is True
    assert files.within_source_scope(tmp_path / "other.md") is False
