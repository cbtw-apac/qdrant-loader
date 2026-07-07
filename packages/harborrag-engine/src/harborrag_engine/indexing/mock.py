from __future__ import annotations

from dataclasses import dataclass

from harborrag_core.domain.document import HarborDocument

from harborrag_engine.indexing.base import BaseIndexer


@dataclass(slots=True)
class MockIndexer(BaseIndexer):
    indexed: list[str]

    def index(self, documents: list[HarborDocument]) -> int:
        self.indexed.extend(doc.id for doc in documents)
        return len(documents)
