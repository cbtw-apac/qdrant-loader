from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from harborrag_core.domain.raw_document import RawDocument
from harborrag_core.domain.source import SourceRecord

from harborrag_adapters.connectors.base import BaseConnector


@dataclass(slots=True)
class MockConnector(BaseConnector):
    """Test-only mock connector for framework tests.

    TODO: Replace this mock with a production connector that supports include/exclude
    globs, checksums, binary-file policy, symlink policy, file-size limits, and object-store persistence for original artifacts.
    """

    provider_name: str = "mock"
    text: str = "# HarborRAG\n\nThis is a mock document for framework tests."

    def discover(self) -> Iterator[SourceRecord]:
        yield SourceRecord(
            id="harbor://mock/doc", source_type="text/markdown", locator="memory://mock"
        )

    def load(self, record: SourceRecord) -> RawDocument:
        return RawDocument(
            record.id,
            record.locator,
            self.text,
            "text/markdown",
            {"title": "Mock Document"},
        )


@dataclass(slots=True)
class MockLocalTextFileConnector(BaseConnector):
    """Test-only local Markdown connector.

    TODO: Replace this mock with a production LocalFileConnector that supports include/exclude
    globs, checksums, binary-file policy, symlink policy, file-size limits, and object-store
    persistence for original artifacts.
    """

    root: Path
    provider_name: str = "mock_local_file"

    def discover(self) -> Iterator[SourceRecord]:
        for path in sorted(self.root.rglob("*.md")):
            yield SourceRecord(
                f"harbor://local/{path.name}",
                "text/markdown",
                str(path),
                {"path": str(path)},
            )

    def load(self, record: SourceRecord) -> RawDocument:
        path = Path(record.locator)
        return RawDocument(
            record.id,
            path.as_uri(),
            path.read_text(encoding="utf-8"),
            "text/markdown",
            {"file_name": path.name},
        )
