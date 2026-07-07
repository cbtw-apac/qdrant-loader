from dataclasses import dataclass

from harborrag_core.domain.retrieval import RetrievalQuery, RetrievalResult


@dataclass(slots=True)
class RetrievalPipeline:
    static_results: list[RetrievalResult]

    def retrieve(self, query: RetrievalQuery) -> list[RetrievalResult]:
        return sorted(self.static_results, key=lambda r: r.score, reverse=True)[
            : query.top_k
        ]
