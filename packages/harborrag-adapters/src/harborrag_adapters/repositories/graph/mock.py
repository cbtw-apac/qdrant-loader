from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from harborrag_core.domain.graph import GraphHint

from harborrag_adapters.repositories.graph.base import BaseGraphRepository


@dataclass(slots=True)
class MockGraphRepository(BaseGraphRepository):
    provider_name: str = "mock_graph"
    edges: list[dict[str, Any]] = field(default_factory=list)

    def upsert_graph_hints(self, hints: Sequence[GraphHint | dict[str, Any]]) -> None:
        for hint in hints:
            self.edges.append(
                hint.as_edge() if isinstance(hint, GraphHint) else dict(hint)
            )
