from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from harborrag_core.domain.retrieval import RetrievalQuery, RetrievalResult


class BaseRetrievalPipeline(ABC):
    """Orchestrate query rewrite, vector/graph retrieval, fusion, reranking, and reconstruction.

    TODO: Implement injectable stages for query rewrite, graph expansion, weighted RRF,
    reranking, permission filtering, and context reconstruction.
    """

    @abstractmethod
    def retrieve(self, query: RetrievalQuery) -> list[RetrievalResult]:
        raise NotImplementedError


class BaseEvidenceBuilder(ABC):
    """Build answer-ready evidence from retrieval results.

    TODO: Add citation spans, source permissions, deduplication, and context-window budgeting.
    """

    @abstractmethod
    def build(self, results: Sequence[RetrievalResult]) -> str:
        raise NotImplementedError
