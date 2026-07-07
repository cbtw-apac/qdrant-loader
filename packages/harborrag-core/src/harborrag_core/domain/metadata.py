from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class DocumentMetadata:
    source_id: str
    source_system: str
    source_url: str | None = None
    author: str | None = None
    project: str | None = None
    repository: str | None = None
    labels: list[str] = field(default_factory=list)
    mime_type: str | None = None
    file_name: str | None = None
    updated_at: datetime | None = None
    custom: dict[str, Any] = field(default_factory=dict)

    def graph_properties(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_system": self.source_system,
            "source_url": self.source_url,
            "author": self.author,
            "project": self.project,
            "repository": self.repository,
            "labels": list(self.labels),
            "mime_type": self.mime_type,
            "file_name": self.file_name,
        }
