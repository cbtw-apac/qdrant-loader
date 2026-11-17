"""Unit tests for the LiteParse PDF provider engine."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from harborrag_adapters.parsers.compat import LiteParseBackend, LiteParseBackendOptions
from harborrag_core.domain.parser import ParseInput

pytestmark = pytest.mark.unit


class FakeLiteParse:
    def __init__(self) -> None:
        self.input: str | bytes | None = None

    def parse(self, input: str | bytes) -> SimpleNamespace:
        self.input = input
        return SimpleNamespace(
            text="Hello\nWorld",
            pages=[
                {
                    "page_num": 1,
                    "text_items": [{"text": "Hello"}, {"text": "World"}],
                }
            ],
        )


@pytest.mark.whitebox
def test_liteparse_backend_uses_llamaindex_liteparse_api_shape():
    fake_parser = FakeLiteParse()

    backend = LiteParseBackend(
        LiteParseBackendOptions(
            parser=fake_parser,
            output_format="markdown",
            ocr_enabled=False,
            target_pages="1-2",
        )
    )

    document = backend.parse_input(ParseInput(content=b"%PDF", filename="report.pdf"))

    assert Path(str(fake_parser.input)).name == "document.pdf"
    assert document.content == "Hello\nWorld"
    assert document.metadata["liteparse_output_format"] == "markdown"
    assert document.metadata["liteparse_ocr_enabled"] is False
    assert document.metadata["liteparse_target_pages"] == "1-2"
    assert document.metadata["page_count"] == 1
    assert document.elements[0].content == "Hello\nWorld"
    assert document.elements[0].metadata["page"] == 1


@pytest.mark.whitebox
def test_liteparse_backend_treats_empty_text_as_empty_not_missing():
    class _FakeEmptyLiteParse:
        def parse(self, _input: str | bytes) -> SimpleNamespace:
            # `text == ""` is a genuine empty extraction; it must not be
            # treated the same as `text is None` and fall back to dumping
            # the whole result object as content.
            return SimpleNamespace(text="", pages=[])

    backend = LiteParseBackend(LiteParseBackendOptions(parser=_FakeEmptyLiteParse()))

    document = backend.parse_input(ParseInput(content=b"%PDF", filename="empty.pdf"))

    assert document.content == ""


@pytest.mark.whitebox
def test_liteparse_constructor_kwargs_match_documented_python_options():
    backend = LiteParseBackend(
        LiteParseBackendOptions(
            output_format="markdown",
            image_mode="off",
            extract_links=False,
            ocr_enabled=False,
            ocr_language="fra",
            target_pages="1-5",
            dpi=300,
            extra_options={"custom_option": "value"},
        )
    )

    assert backend._constructor_kwargs() == {
        "output_format": "markdown",
        "image_mode": "off",
        "extract_links": False,
        "ocr_enabled": False,
        "ocr_language": "fra",
        "target_pages": "1-5",
        "dpi": 300,
        "custom_option": "value",
    }


class _FencedLiteParse:
    """LiteParse fencing ordinary prose it read as a preformatted block."""

    def parse(self, _input: str | bytes) -> SimpleNamespace:
        text = "```python\nPaul Nguyen\nHead of Department\n```\n\nSummary\n"
        return SimpleNamespace(
            text=text,
            pages=[{"page_num": 1, "text": text}],
        )


def test_liteparse_strips_spurious_code_fences_by_default() -> None:
    backend = LiteParseBackend(parser=_FencedLiteParse())

    result = backend.parse_input(ParseInput(content=b"%PDF-1.4", filename="cv.pdf"))

    assert "```" not in result.content
    # Only the delimiters go; the fenced prose is the document's actual text.
    assert "Paul Nguyen" in result.content
    assert "Head of Department" in result.content
    assert "Summary" in result.content


def test_liteparse_strips_fences_from_page_elements_too() -> None:
    backend = LiteParseBackend(parser=_FencedLiteParse())

    result = backend.parse_input(ParseInput(content=b"%PDF-1.4", filename="cv.pdf"))

    assert result.elements
    assert all("```" not in element.content for element in result.elements)
    assert any("Paul Nguyen" in element.content for element in result.elements)


def test_liteparse_keeps_code_fences_when_disabled() -> None:
    backend = LiteParseBackend(parser=_FencedLiteParse(), strip_code_fences=False)

    result = backend.parse_input(ParseInput(content=b"%PDF-1.4", filename="cv.pdf"))

    assert "```python" in result.content


def test_liteparse_strip_code_fences_is_not_a_constructor_argument() -> None:
    # It post-processes LiteParse output; passing it through would raise.
    backend = LiteParseBackend(options=LiteParseBackendOptions(strip_code_fences=True))

    assert "strip_code_fences" not in backend._constructor_kwargs()


@pytest.mark.parametrize("num_workers", [0, -2, 1.5, True, "three"])
def test_liteparse_options_invalid_num_workers_is_rejected(num_workers: object) -> None:
    with pytest.raises(ValueError, match="num_workers must be an integer of at least 1"):
        LiteParseBackendOptions(num_workers=num_workers)  # type: ignore[arg-type]  # invalid on purpose


def test_liteparse_backend_invalid_num_workers_override_is_rejected() -> None:
    with pytest.raises(ValueError, match="got 0"):
        LiteParseBackend(num_workers=0)


@pytest.mark.parametrize("num_workers", [None, 1, 3])
def test_liteparse_options_valid_num_workers_is_kept(num_workers: int | None) -> None:
    assert LiteParseBackendOptions(num_workers=num_workers).num_workers == num_workers
