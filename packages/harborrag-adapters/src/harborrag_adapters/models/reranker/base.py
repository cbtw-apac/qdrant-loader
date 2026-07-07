from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from harborrag_core.ports.models import RerankScore


class BaseReranker(ABC):
    """Base class for reranker adapters.

    TODO: Implement reranker adapters with query/document truncation, score normalization,
    top-k handling, and provider capability metadata.
    """

    provider_name: str

    @abstractmethod
    def rerank(
        self, query: str, documents: Sequence[str], top_k: int | None = None
    ) -> list[RerankScore]:
        raise NotImplementedError
