"""Unit tests for LiteParse engine construction, input modes, and result shapes."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from harborrag_adapters.parsers.errors import ParseError
from harborrag_adapters.parsers.pdf.engines.liteparse.config import LiteParsePDFConfig
from harborrag_adapters.parsers.pdf.engines.liteparse.engine import LiteParsePDFEngine
from harborrag_core.domain.parser import ParseInput

pytestmark = pytest.mark.unit

_PDF = ParseInput(content=b"%PDF-1.4", filename="doc.pdf")


class _RecordingParser:
    """Stands in for `liteparse.LiteParse`, recording its constructor and inputs."""

    instances: list[_RecordingParser] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.inputs: list[str | bytes] = []
        _RecordingParser.instances.append(self)

    def parse(self, value: str | bytes) -> SimpleNamespace:
        self.inputs.append(value)
        return SimpleNamespace(text="Parsed text", pages=None)


class _ResultParser:
    def __init__(self, result: object) -> None:
        self.result = result

    def parse(self, _value: str | bytes) -> object:
        return self.result


def _engine(parser: object, **overrides: Any) -> LiteParsePDFEngine:
    return LiteParsePDFEngine(LiteParsePDFConfig(parser=parser, **overrides))


@pytest.fixture
def fake_liteparse_module(monkeypatch: pytest.MonkeyPatch) -> type[_RecordingParser]:
    module = ModuleType("liteparse")
    module.LiteParse = _RecordingParser  # type: ignore[attr-defined]
    _RecordingParser.instances = []
    monkeypatch.setitem(sys.modules, "liteparse", module)
    return _RecordingParser


def test_capabilities_follow_ocr_option() -> None:
    assert LiteParsePDFEngine(ocr_enabled=True).supports_ocr is True
    assert LiteParsePDFEngine(ocr_enabled=False).supports_ocr is False
    assert LiteParsePDFEngine().supports_layout is True


def test_blank_ocr_server_url_is_treated_as_unset() -> None:
    engine = LiteParsePDFEngine(ocr_server_url="   ", tessdata_path=Path("/opt/tessdata"))

    kwargs = engine._constructor_kwargs()

    assert "ocr_server_url" not in kwargs
    assert kwargs["tessdata_path"] == "/opt/tessdata"


def test_parser_is_built_once_from_liteparse_and_reused(
    fake_liteparse_module: type[_RecordingParser],
) -> None:
    engine = LiteParsePDFEngine(ocr_enabled=False, max_pages=3)

    first = engine.parse_input(_PDF)
    second = engine.parse_input(_PDF)

    assert first.content == second.content == "Parsed text"
    assert len(fake_liteparse_module.instances) == 1
    built = fake_liteparse_module.instances[0]
    assert built.kwargs["ocr_enabled"] is False
    assert built.kwargs["max_pages"] == 3
    assert len(built.inputs) == 2


def test_missing_liteparse_package_explains_how_to_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "liteparse", None)

    with pytest.raises(ImportError, match=r"harborrag-adapters\[pdf-liteparse\]"):
        LiteParsePDFEngine().parse_input(_PDF)


def test_parser_errors_are_wrapped_as_parse_errors() -> None:
    class _Broken:
        def parse(self, _value: str | bytes) -> object:
            raise RuntimeError("corrupt xref table")

    with pytest.raises(ParseError, match="LiteParse could not parse PDF: corrupt xref table"):
        _engine(_Broken()).parse_input(_PDF)


def test_parser_without_parse_method_is_reported() -> None:
    with pytest.raises(ParseError, match="does not expose `parse`"):
        _engine(object()).parse_input(_PDF)


def test_bytes_input_mode_passes_raw_bytes() -> None:
    parser = _RecordingParser()

    _engine(parser, input_mode=" Bytes ").parse_input(_PDF)

    assert parser.inputs == [b"%PDF-1.4"]


def test_unknown_input_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="LiteParse input_mode must be one of bytes, path"):
        _engine(_RecordingParser(), input_mode="stream")


def test_result_without_text_falls_back_to_whole_result() -> None:
    result = _engine(_ResultParser("plain string result")).parse_input(_PDF)

    assert result.content == "plain string result"
    assert result.metadata["page_count"] is None
    assert result.elements[0].content == "plain string result"


def test_unsized_pages_report_no_page_count() -> None:
    pages = iter([{"page_number": "2", "text": "Second page"}])
    result = _engine(_ResultParser(SimpleNamespace(text="Second page", pages=pages))).parse_input(
        _PDF
    )

    assert result.metadata["page_count"] is None


def test_object_pages_use_attributes_and_fallback_numbering() -> None:
    pages = [
        SimpleNamespace(page_num=None, page_number=None, page="7", text="Seventh"),
        SimpleNamespace(page_num="n/a", text=None, text_items=[SimpleNamespace(text="Item")]),
        SimpleNamespace(text=None, text_items=[SimpleNamespace(text=""), {"text": "Dict item"}]),
        {"page": 9, "textItems": [{"text": ""}]},
    ]
    result = _engine(_ResultParser(SimpleNamespace(text="All", pages=pages))).parse_input(_PDF)

    assert [(element.metadata["page"], element.content) for element in result.elements] == [
        (7, "Seventh"),
        (2, "Item"),
        (3, "Dict item"),
    ]
    assert result.metadata["page_count"] == 4


def test_pages_with_only_fences_are_dropped_in_favour_of_content() -> None:
    pages = [{"page_num": 1, "text": "```\n```"}]
    result = _engine(_ResultParser(SimpleNamespace(text="Body", pages=pages))).parse_input(_PDF)

    assert [element.content for element in result.elements] == ["Body"]


def test_raw_is_omitted_unless_requested() -> None:
    result = _engine(_ResultParser(SimpleNamespace(text="Body", pages=[]))).parse_input(_PDF)

    assert result.raw is None


def test_raw_prefers_model_dump() -> None:
    class _Pydantic:
        text = "Body"
        pages: list[object] = []

        def model_dump(self) -> dict[str, str]:
            return {"text": "Body"}

    result = _engine(_ResultParser(_Pydantic()), include_raw=True).parse_input(_PDF)

    assert result.raw == {"liteparse_result": {"text": "Body"}}


def test_raw_falls_back_to_dict_then_content() -> None:
    class _Legacy:
        text = "Body"
        pages: list[object] = []

        def dict(self) -> dict[str, str]:
            return {"legacy": "yes"}

    legacy = _engine(_ResultParser(_Legacy()), include_raw=True).parse_input(_PDF)
    plain = _engine(_ResultParser("just text"), include_raw=True).parse_input(_PDF)

    assert legacy.raw == {"liteparse_result": {"legacy": "yes"}}
    assert plain.raw == {"liteparse_result": "just text"}
