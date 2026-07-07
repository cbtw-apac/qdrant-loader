from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseCacheRepository(ABC):
    """Base class for cache/state repositories.

    TODO: Implement real repositories with TTL behavior, namespaced keys, serialization policy,
    distributed locks where supported, and testable expiry semantics.
    """

    provider_name: str

    @abstractmethod
    def get(self, key: str) -> Any | None:
        raise NotImplementedError

    @abstractmethod
    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        raise NotImplementedError
