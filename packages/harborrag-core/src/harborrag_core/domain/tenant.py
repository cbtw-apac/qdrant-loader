from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Tenant:
    id: str = "default"

    def __post_init__(self) -> None:
        if not self.id or any(ch.isspace() for ch in self.id):
            raise ValueError("Tenant id must be non-empty and contain no whitespace.")
