from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

from harborrag_core.domain.retrieval import RetrievalResult


class BaseVectorRepository(ABC):
    """Base class for vector repositories.

    TODO: Implement real repositories by supporting collection setup, dense/sparse/hybrid
    search requests, payload filters, batch upsert, and deterministic provider capability metadata.
    """

    provider_name: str

    @abstractmethod
    def upsert(self, items: Sequence[dict[str, Any]]) -> None:
        raise NotImplementedError

    @abstractmethod
    def search(self, vector: Sequence[float], top_k: int = 10) -> list[RetrievalResult]:
        raise NotImplementedError
