from __future__ import annotations

from typing import Protocol

from harborrag_core.domain.parsed_document import ParsedDocument
from harborrag_core.domain.raw_document import RawDocument


class ParserPort(Protocol):
    parser_name: str

    def parse(self, raw: RawDocument) -> ParsedDocument: ...
