from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from harborrag_core.domain.retrieval import RetrievalResult

from harborrag_adapters.repositories.vector.base import BaseVectorRepository


@dataclass(slots=True)
class MockVectorRepository(BaseVectorRepository):
    provider_name: str = "mock_vector"
    items: list[dict[str, Any]] = field(default_factory=list)

    def upsert(self, items: Sequence[dict[str, Any]]) -> None:
        self.items.extend(dict(item) for item in items)

    def search(self, vector: Sequence[float], top_k: int = 10) -> list[RetrievalResult]:
        results = [
            RetrievalResult(
                str(item["id"]),
                str(item.get("text", "")),
                float(
                    sum(
                        a * b
                        for a, b in zip(vector, item.get("vector", []), strict=False)
                    )
                ),
                dict(item.get("metadata", {})),
            )
            for item in self.items
        ]
        return sorted(results, key=lambda r: r.score, reverse=True)[:top_k]
