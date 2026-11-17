"""Parser and PDF backend constructors that a YAML parser catalog can name.

A parser's or backend's option class owns the checks on its setting values.
Those checks need no installed parser library, so the catalog loader runs them.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields
from typing import Any

from harborrag_adapters.parsers.common.base import HarborParser
from harborrag_adapters.parsers.common.limits import PDF_MAX_PAGES
from harborrag_adapters.parsers.document.engines.docx.engine import DocxDocumentEngine
from harborrag_adapters.parsers.document.engines.epub.engine import EpubDocumentEngine
from harborrag_adapters.parsers.document.parser import HarborDocumentParser
from harborrag_adapters.parsers.factory import HarborParserFactory
from harborrag_adapters.parsers.image.engines.ocr.engine import OcrImageEngine
from harborrag_adapters.parsers.image.parser import HarborImageParser
from harborrag_adapters.parsers.markup.engines.html.engine import HtmlMarkupEngine
from harborrag_adapters.parsers.markup.engines.markdown.engine import MarkdownMarkupEngine
from harborrag_adapters.parsers.markup.parser import HarborMarkupParser
from harborrag_adapters.parsers.pdf.base import HarborPDFEngine
from harborrag_adapters.parsers.pdf.config import PDFParserConfig, PDFRouterConfig
from harborrag_adapters.parsers.pdf.engines.docling.config import (
    DoclingPDFConfig,
)
from harborrag_adapters.parsers.pdf.engines.docling.engine import (
    DoclingPDFEngine,
)
from harborrag_adapters.parsers.pdf.engines.liteparse.config import (
    LiteParsePDFConfig,
)
from harborrag_adapters.parsers.pdf.engines.liteparse.engine import (
    LiteParsePDFEngine,
)
from harborrag_adapters.parsers.pdf.engines.mineru.config import (
    MinerUPDFConfig,
)
from harborrag_adapters.parsers.pdf.engines.mineru.engine import (
    MinerUPDFEngine,
)
from harborrag_adapters.parsers.pdf.engines.paddleocr.config import (
    PaddleOCRPDFConfig,
)
from harborrag_adapters.parsers.pdf.engines.paddleocr.engine import (
    PaddleOCRPDFEngine,
)
from harborrag_adapters.parsers.pdf.engines.pymupdf.engine import PyMuPDFEngine
from harborrag_adapters.parsers.pdf.parser import HarborPDFParser
from harborrag_adapters.parsers.presentation.engines.python_pptx.engine import (
    PythonPptxPresentationEngine,
)
from harborrag_adapters.parsers.presentation.parser import HarborPresentationParser
from harborrag_adapters.parsers.spreadsheet.engines.csv.engine import (
    CsvSpreadsheetEngine,
)
from harborrag_adapters.parsers.spreadsheet.engines.openpyxl.engine import (
    ExcelSpreadsheetEngine,
)
from harborrag_adapters.parsers.spreadsheet.parser import HarborSpreadsheetParser
from harborrag_adapters.parsers.structured.engines.json.engine import (
    JsonStructuredEngine,
)
from harborrag_adapters.parsers.structured.parser import HarborStructuredParser
from harborrag_adapters.parsers.text.engines.plain_text.engine import PlainTextEngine
from harborrag_adapters.parsers.text.parser import HarborTextParser

type ParserFactory = Callable[..., HarborParser]
type PdfBackendFactory = Callable[..., HarborPDFEngine]
type OptionFactory = Callable[..., object]
type SettingsCheck = Callable[[Mapping[str, Any]], None]


def _document_parser(engine: object) -> HarborDocumentParser:
    return HarborDocumentParser((engine,))  # type: ignore[arg-type]


def _spreadsheet_parser(engine: object) -> HarborSpreadsheetParser:
    return HarborSpreadsheetParser((engine,))  # type: ignore[arg-type]


def _presentation_parser(engine: object) -> HarborPresentationParser:
    return HarborPresentationParser((engine,))  # type: ignore[arg-type]


def _markup_parser(engine: object) -> HarborMarkupParser:
    return HarborMarkupParser((engine,))  # type: ignore[arg-type]


def _structured_parser(engine: object) -> HarborStructuredParser:
    return HarborStructuredParser((engine,))  # type: ignore[arg-type]


def _text_parser(engine: object) -> HarborTextParser:
    return HarborTextParser((engine,))  # type: ignore[arg-type]


def _csv_factory(**settings: Any) -> HarborSpreadsheetParser:
    return _spreadsheet_parser(CsvSpreadsheetEngine(**settings))


def _docx_factory(**settings: Any) -> HarborDocumentParser:
    return _document_parser(DocxDocumentEngine(**settings))


def _epub_factory(**settings: Any) -> HarborDocumentParser:
    return _document_parser(EpubDocumentEngine(**settings))


def _excel_factory(**settings: Any) -> HarborSpreadsheetParser:
    return _spreadsheet_parser(ExcelSpreadsheetEngine(**settings))


def _html_factory(**settings: Any) -> HarborMarkupParser:
    return _markup_parser(HtmlMarkupEngine(**settings))


def _markdown_factory(**settings: Any) -> HarborMarkupParser:
    return _markup_parser(MarkdownMarkupEngine(**settings))


def _pptx_factory(**settings: Any) -> HarborPresentationParser:
    return _presentation_parser(PythonPptxPresentationEngine(**settings))


def _json_factory(**settings: Any) -> HarborStructuredParser:
    return _structured_parser(JsonStructuredEngine(**settings))


def _text_factory(**settings: Any) -> HarborTextParser:
    return _text_parser(PlainTextEngine(**settings))


def _image_factory(**settings: Any) -> HarborImageParser:
    return HarborImageParser((OcrImageEngine(**settings),))


def _pdf_factory(
    *,
    backends: list[HarborPDFEngine] | None = None,
    min_content_chars: int = 20,
    max_pages: int | None = PDF_MAX_PAGES,
    profile: str = "liteparse",
) -> HarborPDFParser:
    if backends is not None:
        return HarborPDFParser(
            backends=backends,
            min_content_chars=min_content_chars,
            max_pages=max_pages,
            profile=profile,
        )
    router = PDFRouterConfig(default_profile=profile)
    return HarborParserFactory().create_pdf_parser(
        PDFParserConfig(
            min_content_chars=min_content_chars,
            max_pages=max_pages,
            router=router,
        )
    )


def _check_image_settings(settings: Mapping[str, Any]) -> None:
    """Build the image OCR engine's options, which check the values given."""
    OcrImageEngine(**settings)


def _check_pdf_settings(settings: Mapping[str, Any]) -> None:
    """Build the PDF parser's config objects, which check the values given."""
    limits = {name: value for name, value in settings.items() if name != "profile"}
    PDFParserConfig(**limits)
    if "profile" in settings:
        PDFRouterConfig(default_profile=settings["profile"])


_PARSER_FACTORIES: Mapping[str, ParserFactory] = {
    "csv": _csv_factory,
    "docx": _docx_factory,
    "epub": _epub_factory,
    "excel": _excel_factory,
    "html": _html_factory,
    "image": _image_factory,
    "json": _json_factory,
    "markdown": _markdown_factory,
    "pdf": _pdf_factory,
    "pptx": _pptx_factory,
    "text": _text_factory,
}


@dataclass(frozen=True, slots=True)
class PdfBackendSpec:
    """Constructor metadata for one declaratively configurable PDF backend."""

    factory: PdfBackendFactory
    option_factory: OptionFactory | None = None

    def setting_names(self) -> set[str]:
        """Return YAML option names accepted by this backend."""
        if self.option_factory is None:
            return set()
        return {item.name for item in fields(self.option_factory)}  # type: ignore[arg-type]

    def check_settings(self, settings: Mapping[str, Any]) -> None:
        """Run the backend's own value checks on YAML settings without building it.

        Args:
            settings: Backend option names and their YAML values.

        Raises:
            TypeError: A setting has a type the backend's options cannot check.
            ValueError: The backend's options reject a setting's value.
        """
        if self.option_factory is not None:
            self.option_factory(**settings)

    def build(self, settings: Mapping[str, Any]) -> HarborPDFEngine:
        """Construct a backend and its typed options from YAML settings."""
        if self.option_factory is None:
            return self.factory(**settings)
        options = self.option_factory(**settings)
        return self.factory(options)


_PARSER_SETTING_NAMES: Mapping[str, frozenset[str]] = {
    **{name: frozenset() for name in _PARSER_FACTORIES if name not in {"image", "pdf"}},
    "image": frozenset({"config", "lang", "max_pixels", "ocr_engine", "ocr_server_url", "timeout"}),
    "pdf": frozenset({"max_pages", "min_content_chars", "profile"}),
}
_PARSER_FAMILIES: Mapping[str, str] = {
    "csv": HarborSpreadsheetParser.parser_name,
    "docx": HarborDocumentParser.parser_name,
    "epub": HarborDocumentParser.parser_name,
    "excel": HarborSpreadsheetParser.parser_name,
    "html": HarborMarkupParser.parser_name,
    "image": HarborImageParser.parser_name,
    "json": HarborStructuredParser.parser_name,
    "markdown": HarborMarkupParser.parser_name,
    "pdf": HarborPDFParser.parser_name,
    "pptx": HarborPresentationParser.parser_name,
    "text": HarborTextParser.parser_name,
}
_PARSER_SETTING_CHECKS: Mapping[str, SettingsCheck] = {
    "image": _check_image_settings,
    "pdf": _check_pdf_settings,
}
_PDF_BACKENDS: Mapping[str, PdfBackendSpec] = {
    "docling": PdfBackendSpec(DoclingPDFEngine, DoclingPDFConfig),
    "liteparse": PdfBackendSpec(LiteParsePDFEngine, LiteParsePDFConfig),
    "mineru": PdfBackendSpec(MinerUPDFEngine, MinerUPDFConfig),
    "paddleocr": PdfBackendSpec(PaddleOCRPDFEngine, PaddleOCRPDFConfig),
    "pymupdf": PdfBackendSpec(PyMuPDFEngine),
}

PDF_BACKEND_SECRET_FIELDS = frozenset({"password"})
PDF_BACKEND_PYTHON_ONLY_FIELDS = frozenset({"converter", "env", "parser", "pipeline_options"})


def parser_factory(parser: str) -> ParserFactory | None:
    """Return a parser constructor by stable parser name."""
    return _PARSER_FACTORIES.get(parser)


def parser_setting_names(parser: str) -> frozenset[str]:
    """Return YAML settings accepted by a parser constructor."""
    return _PARSER_SETTING_NAMES.get(parser, frozenset())


def parser_family(parser: str) -> str:
    """Return the name of the parser family a supported parser type configures."""
    return _PARSER_FAMILIES[parser]


def check_parser_settings(parser: str, settings: Mapping[str, Any]) -> None:
    """Run the parser's own value checks on YAML settings without building it.

    Args:
        parser: Stable parser type, such as ``pdf`` or ``image``.
        settings: Parser setting names and their YAML values.

    Raises:
        TypeError: A setting has a type the parser's options cannot check.
        ValueError: The parser's options reject a setting's value.
    """
    check = _PARSER_SETTING_CHECKS.get(parser)
    if check is not None:
        check(settings)


def supported_parser_names() -> list[str]:
    """Return configurable parser names in stable display order."""
    return sorted(_PARSER_FACTORIES)


def pdf_backend_spec(backend: str) -> PdfBackendSpec | None:
    """Return constructor metadata for a PDF backend name."""
    return _PDF_BACKENDS.get(backend)


def supported_pdf_backend_names() -> list[str]:
    """Return configurable PDF backend names in deterministic order."""
    return sorted(_PDF_BACKENDS)
