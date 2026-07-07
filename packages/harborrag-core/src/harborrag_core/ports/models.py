from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class ChatResponse:
    text: str


@dataclass(slots=True)
class EmbeddingResponse:
    vectors: list[list[float]]


@dataclass(slots=True)
class RerankScore:
    index: int
    score: float


class ChatModelPort(Protocol):
    def respond(self, messages: str) -> ChatResponse: ...


class EmbeddingModelPort(Protocol):
    def embed(self, texts: Sequence[str]) -> EmbeddingResponse: ...


class RerankerPort(Protocol):
    def rerank(
        self, query: str, documents: Sequence[str], top_k: int | None = None
    ) -> list[RerankScore]: ...
