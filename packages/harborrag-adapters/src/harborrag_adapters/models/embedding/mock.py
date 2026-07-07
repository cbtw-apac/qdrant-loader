from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256

from harborrag_core.ports.models import EmbeddingResponse

from harborrag_adapters.models.embedding.base import BaseEmbeddingModel


@dataclass(slots=True)
class MockEmbeddingModel(BaseEmbeddingModel):
    """Test-only mock embedding model for framework tests."""

    dimensions: int = 8
    provider_name: str = "mock_embed"

    def embed(self, texts: Sequence[str]) -> EmbeddingResponse:
        return EmbeddingResponse(vectors=[self._vector(text) for text in texts])

    def _vector(self, text: str) -> list[float]:
        digest = sha256(text.encode("utf-8")).digest()
        return [round(digest[i] / 255.0, 6) for i in range(self.dimensions)]
