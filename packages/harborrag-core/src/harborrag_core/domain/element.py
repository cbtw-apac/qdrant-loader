from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ElementType = Literal["heading", "paragraph", "table", "image", "code", "metadata"]


@dataclass(slots=True)
class DocumentElement:
    id: str
    type: ElementType
    text: str | None = None
    markdown: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def display_text(self) -> str:
        return self.text or self.markdown or ""
