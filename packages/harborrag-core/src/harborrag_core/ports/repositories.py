from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from harborrag_core.domain.graph import GraphHint
from harborrag_core.domain.retrieval import RetrievalResult


class VectorRepositoryPort(Protocol):
    def upsert(self, items: Sequence[dict[str, Any]]) -> None: ...
    def search(
        self, vector: Sequence[float], top_k: int = 10
    ) -> list[RetrievalResult]: ...


class GraphRepositoryPort(Protocol):
    def upsert_graph_hints(self, hints: Sequence[GraphHint]) -> None: ...


class CacheRepositoryPort(Protocol):
    def get(self, key: str) -> Any | None: ...
    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None: ...


class ObjectRepositoryPort(Protocol):
    def put_bytes(
        self, key: str, data: bytes, content_type: str | None = None
    ) -> str: ...
    def get_bytes(self, key: str) -> bytes: ...


class DatabaseRepositoryPort(Protocol):
    def execute(
        self, statement: str, parameters: Sequence[Any] | None = None
    ) -> list[dict[str, Any]]: ...
