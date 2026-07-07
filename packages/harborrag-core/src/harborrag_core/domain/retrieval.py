from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RetrievalQuery:
    text: str
    top_k: int = 10
    filters: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RetrievalResult:
    id: str
    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)
