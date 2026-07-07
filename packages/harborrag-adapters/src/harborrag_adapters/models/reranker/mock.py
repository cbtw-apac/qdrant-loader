from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from harborrag_core.ports.models import RerankScore

from harborrag_adapters.models.reranker.base import BaseReranker


@dataclass(slots=True)
class MockReranker(BaseReranker):
    """Test-only mock reranker for framework tests."""

    provider_name: str = "mock_rerank"

    def rerank(
        self, query: str, documents: Sequence[str], top_k: int | None = None
    ) -> list[RerankScore]:
        q = Counter(query.lower().split())
        scores = [
            RerankScore(i, float(sum((Counter(d.lower().split()) & q).values())))
            for i, d in enumerate(documents)
        ]
        scores.sort(key=lambda item: item.score, reverse=True)
        return scores[:top_k] if top_k else scores
