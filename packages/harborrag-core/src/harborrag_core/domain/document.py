from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from harborrag_core.domain.element import DocumentElement
from harborrag_core.domain.graph import GraphHint
from harborrag_core.domain.metadata import DocumentMetadata
from harborrag_core.domain.provenance import DocumentProvenance


@dataclass(slots=True)
class HarborDocument:
    id: str
    source: str
    source_type: str
    content_type: str
    title: str | None
    text: str
    metadata: DocumentMetadata
    provenance: DocumentProvenance
    elements: list[DocumentElement] = field(default_factory=list)
    graph_hints: list[GraphHint] = field(default_factory=list)
    ingested_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    raw: dict[str, Any] = field(default_factory=dict)

    def vector_payload(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, **self.metadata.graph_properties()}
