from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from harborrag_core.domain.element import DocumentElement


@dataclass(slots=True)
class ParseQuality:
    score: float
    warnings: list[str] = field(default_factory=list)

    @property
    def acceptable(self) -> bool:
        return self.score >= 0.5


@dataclass(slots=True)
class ParsedDocument:
    text: str
    elements: list[DocumentElement]
    parser_name: str
    markdown: str | None = None
    parse_quality: ParseQuality = field(default_factory=lambda: ParseQuality(score=1.0))
    raw: dict[str, Any] = field(default_factory=dict)
