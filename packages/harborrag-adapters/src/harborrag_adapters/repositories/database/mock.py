from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from harborrag_adapters.repositories.database.base import BaseDatabaseRepository


@dataclass(slots=True)
class MockDatabaseRepository(BaseDatabaseRepository):
    provider_name: str = "mock_database"
    statements: list[tuple[str, tuple[Any, ...]]] = field(default_factory=list)

    def execute(
        self, statement: str, parameters: Sequence[Any] | None = None
    ) -> list[dict[str, Any]]:
        self.statements.append((statement, tuple(parameters or ())))
        return []
