from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SourceRecord:
    id: str
    source_type: str
    locator: str
    metadata: dict[str, Any] = field(default_factory=dict)
