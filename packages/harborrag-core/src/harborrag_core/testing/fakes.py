from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from harborrag_core.domain.element import DocumentElement
from harborrag_core.domain.parsed_document import ParsedDocument
from harborrag_core.domain.raw_document import RawDocument
from harborrag_core.domain.source import SourceRecord


@dataclass(slots=True)
class FakeConnector:
    provider_name: str = "fake"
    documents: list[RawDocument] = field(default_factory=list)

    def discover(self) -> Iterable[SourceRecord]:
        for raw in self.documents:
            yield SourceRecord(
                id=raw.id, source_type=raw.content_type, locator=raw.source
            )

    def load(self, record: SourceRecord) -> RawDocument:
        for raw in self.documents:
            if raw.id == record.id:
                return raw
        raise KeyError(record.id)


@dataclass(slots=True)
class FakeParser:
    parser_name: str = "fake"

    def parse(self, raw: RawDocument) -> ParsedDocument:
        text = raw.text()
        return ParsedDocument(
            text=text,
            parser_name=self.parser_name,
            elements=[DocumentElement(id=f"{raw.id}:0", type="paragraph", text=text)],
        )
