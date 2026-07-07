from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from harborrag_adapters.repositories.cache.base import BaseCacheRepository


@dataclass(slots=True)
class MockCacheRepository(BaseCacheRepository):
    provider_name: str = "mock_cache"
    values: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str) -> Any | None:
        return self.values.get(key)

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        self.values[key] = value
