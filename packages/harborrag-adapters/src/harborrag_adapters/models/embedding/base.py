from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from harborrag_core.ports.models import EmbeddingResponse


class BaseEmbeddingModel(ABC):
    """Base class for embedding adapters.

    TODO: Implement provider adapters with batch sizing, retry policy, dimensionality checks,
    and deterministic error messages for missing optional dependencies.
    """

    provider_name: str

    @abstractmethod
    def embed(self, texts: Sequence[str]) -> EmbeddingResponse:
        raise NotImplementedError
