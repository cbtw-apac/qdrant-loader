from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from harborrag_core.domain.raw_document import RawDocument
from harborrag_core.domain.source import SourceRecord


class ConnectorPort(Protocol):
    provider_name: str

    def discover(self) -> Iterable[SourceRecord]: ...
    def load(self, record: SourceRecord) -> RawDocument: ...
