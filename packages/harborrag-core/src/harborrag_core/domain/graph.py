from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class GraphHint:
    subject_id: str
    predicate: str
    object_id: str
    subject_type: str
    object_type: str
    confidence: float = 1.0
    properties: dict[str, Any] = field(default_factory=dict)

    def as_edge(self) -> dict[str, Any]:
        return {
            "source_id": self.subject_id,
            "target_id": self.object_id,
            "relation": self.predicate,
            "confidence": self.confidence,
            "properties": self.properties,
        }
