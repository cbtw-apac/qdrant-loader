from __future__ import annotations

from abc import ABC, abstractmethod

from harborrag_core.domain.document import HarborDocument
from harborrag_core.domain.graph import GraphHint


class BaseGraphMapper(ABC):
    """Map normalized documents into graph hints.

    TODO: Implement source-specific mappers for Jira, Confluence, GitHub, files, and web.
    Keep provider-neutral GraphHint as the output type.
    """

    @abstractmethod
    def map_document(self, document: HarborDocument) -> list[GraphHint]:
        raise NotImplementedError
