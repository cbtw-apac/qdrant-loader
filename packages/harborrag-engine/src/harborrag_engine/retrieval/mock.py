from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from harborrag_core.domain.retrieval import RetrievalQuery, RetrievalResult

from harborrag_engine.retrieval.base import BaseEvidenceBuilder, BaseRetrievalPipeline


@dataclass(slots=True)
class MockRetrievalPipeline(BaseRetrievalPipeline):
    results: list[RetrievalResult] = field(default_factory=list)

    def retrieve(self, query: RetrievalQuery) -> list[RetrievalResult]:
        terms = set(query.text.lower().split())
        ranked = [
            RetrievalResult(
                r.id,
                r.text,
                r.score + len(terms.intersection(r.text.lower().split())),
                r.metadata,
            )
            for r in self.results
        ]
        return sorted(ranked, key=lambda item: item.score, reverse=True)[: query.top_k]


class MockEvidenceBuilder(BaseEvidenceBuilder):
    def build(self, results: Sequence[RetrievalResult]) -> str:
        return "\n\n".join(
            f"[{idx}] {item.text}" for idx, item in enumerate(results, start=1)
        )
