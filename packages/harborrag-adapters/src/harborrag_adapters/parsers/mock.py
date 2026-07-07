from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from harborrag_core.domain.element import DocumentElement
from harborrag_core.domain.parsed_document import ParsedDocument
from harborrag_core.domain.raw_document import RawDocument

from harborrag_adapters.parsers.base import BaseParser


@dataclass(slots=True)
class MockMarkdownParser(BaseParser):
    parser_name: str = "mock_markdown"

    def parse(self, raw: RawDocument) -> ParsedDocument:
        text = raw.text()
        elements: list[DocumentElement] = []
        for idx, block in enumerate([b for b in text.split("\n\n") if b.strip()]):
            element_type: Literal["heading", "paragraph"] = (
                "heading" if block.strip().startswith("#") else "paragraph"
            )
            clean = block.strip().lstrip("#").strip()
            elements.append(
                DocumentElement(
                    id=f"{raw.id}:{idx}", type=element_type, text=clean, markdown=block
                )
            )
        return ParsedDocument(
            text=text, markdown=text, elements=elements, parser_name=self.parser_name
        )
