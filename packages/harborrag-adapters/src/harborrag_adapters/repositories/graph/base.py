from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from harborrag_core.domain.graph import GraphHint


class BaseGraphRepository(ABC):
    """Base class for graph repositories.

    TODO: Implement real repositories by mapping GraphHint into provider-native nodes/edges,
    adding idempotent upserts, tenant labels, and query-safe relationship names.
    """

    provider_name: str

    @abstractmethod
    def upsert_graph_hints(self, hints: Sequence[GraphHint]) -> None:
        raise NotImplementedError
