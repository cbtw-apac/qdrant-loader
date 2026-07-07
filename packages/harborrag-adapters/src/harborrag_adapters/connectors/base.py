from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from harborrag_core.domain.raw_document import RawDocument
from harborrag_core.domain.source import SourceRecord


class BaseConnector(ABC):
    """Base class for connector adapters.

    TODO: Implement real connectors by subclassing this class, mapping provider-native
    records into SourceRecord in discover(), and loading provider-native content into
    RawDocument in load(). Keep authentication, pagination, retries, and provider SDK
    details inside the concrete connector folder.
    """

    provider_name: str

    @abstractmethod
    def discover(self) -> Iterable[SourceRecord]:
        raise NotImplementedError

    @abstractmethod
    def load(self, record: SourceRecord) -> RawDocument:
        raise NotImplementedError
