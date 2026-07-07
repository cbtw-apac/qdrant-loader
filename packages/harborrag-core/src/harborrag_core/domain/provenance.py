from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(slots=True)
class DocumentProvenance:
    connector_name: str
    parser_name: str | None = None
    connector_version: str | None = None
    parser_version: str | None = None
    checksum: str | None = None
    ingested_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    raw: dict[str, Any] = field(default_factory=dict)
