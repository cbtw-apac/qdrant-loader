from __future__ import annotations

from harborrag_core.domain.document import HarborDocument
from harborrag_core.domain.graph import GraphHint

from harborrag_engine.graph.base import BaseGraphMapper


class MockGraphMapper(BaseGraphMapper):
    def map_document(self, document: HarborDocument) -> list[GraphHint]:
        return list(document.graph_hints)
