from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any


class BaseDatabaseRepository(ABC):
    """Base class for SQL/document repositories.

    TODO: Implement real repositories with parameterized queries, transaction policy,
    migration hooks, and safe table/collection name validation.
    """

    provider_name: str

    @abstractmethod
    def execute(
        self, statement: str, parameters: Sequence[Any] | None = None
    ) -> list[dict[str, Any]]:
        raise NotImplementedError
