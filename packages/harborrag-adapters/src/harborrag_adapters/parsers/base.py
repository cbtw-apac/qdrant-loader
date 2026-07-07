from __future__ import annotations

from abc import ABC, abstractmethod

from harborrag_core.domain.parsed_document import ParsedDocument
from harborrag_core.domain.raw_document import RawDocument


class BaseParser(ABC):
    """Base class for parser adapters.

    TODO: Implement parser engines by converting RawDocument into ParsedDocument. Preserve
    parser name/version, parse quality, warnings, element-level structure, tables, images,
    and raw diagnostics when the provider exposes them.
    """

    parser_name: str

    @abstractmethod
    def parse(self, raw: RawDocument) -> ParsedDocument:
        raise NotImplementedError
