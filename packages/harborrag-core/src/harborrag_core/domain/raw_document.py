from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RawDocument:
    id: str
    source: str
    content: bytes | str
    content_type: str
    metadata: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def text(self) -> str:
        return (
            self.content.decode("utf-8", errors="replace")
            if isinstance(self.content, bytes)
            else self.content
        )
