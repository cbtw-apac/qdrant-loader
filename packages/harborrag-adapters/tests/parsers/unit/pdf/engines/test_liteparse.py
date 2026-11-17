"""Unit tests for the LiteParse PDF provider engine."""

from __future__ import annotations

import re
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


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("output_format", "nonsense"),
        ("image_mode", "nonsense"),
        ("input_mode", "stream"),
        ("dpi", 0),
        ("dpi", "150"),
        ("dpi", True),
        ("max_pages", 0),
        ("max_pages", 1.5),
        ("ocr_language", 5),
        ("target_pages", 3),
        ("ocr_enabled", "yes"),
        ("extract_links", 1),
        ("quiet", "no"),
        ("strip_code_fences", "false"),
        ("tessdata_path", 5),
        ("input_mode", None),
    ],
)
def test_liteparse_options_value_outside_permitted_set_is_rejected(
    option: str,
    value: object,
) -> None:
    expected = f"LiteParse {option} must be .*got {re.escape(repr(value))}"

    with pytest.raises(ValueError, match=expected):
        LiteParseBackendOptions(**{option: value})


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("output_format", "json"),
        ("output_format", "text"),
        ("image_mode", "embed"),
        ("image_mode", "none"),
        ("image_mode", "off"),
        ("input_mode", "bytes"),
        ("dpi", 96.5),
        ("max_pages", 1),
        ("target_pages", "1-5,10"),
        ("quiet", None),
        ("tessdata_path", Path("/usr/share/tessdata")),
        ("extra_options", {"skip_diagonal_text": True}),
    ],
)
def test_liteparse_options_permitted_value_is_kept(option: str, value: object) -> None:
    assert getattr(LiteParseBackendOptions(**{option: value}), option) == value


@pytest.mark.parametrize(
    ("option", "written", "kept"),
    [
        ("output_format", " Markdown ", "markdown"),
        ("image_mode", "OFF", "off"),
        ("input_mode", " Bytes ", "bytes"),
    ],
)
def test_liteparse_options_choice_is_kept_lowercase_and_trimmed(
    option: str,
    written: str,
    kept: str,
) -> None:
    assert getattr(LiteParseBackendOptions(**{option: written}), option) == kept


@pytest.mark.parametrize(
    "option",
    [
        "output_format",
        "image_mode",
        "extract_links",
        "ocr_enabled",
        "ocr_language",
        "include_raw",
        "strip_code_fences",
    ],
)
def test_liteparse_options_explicit_none_is_kept(option: str) -> None:
    assert getattr(LiteParseBackendOptions(**{option: None}), option) is None


@pytest.mark.parametrize(
    "option",
    ["ocr_language", "ocr_server_url", "target_pages", "tessdata_path"],
)
def test_liteparse_options_blank_text_is_unset(option: str) -> None:
    assert getattr(LiteParseBackendOptions(**{option: "  "}), option) is None


def test_liteparse_options_false_image_mode_is_off() -> None:
    assert LiteParseBackendOptions(image_mode=False).image_mode == "off"  # type: ignore[arg-type]  # YAML reads an unquoted off as false


def test_liteparse_options_rejected_ocr_server_url_is_not_shown() -> None:
    wrong_shape = {"url": "https://reader:synthetic-token@ocr.example.test/ocr"}

    with pytest.raises(ValueError, match="LiteParse ocr_server_url must be .*got dict") as error:
        LiteParseBackendOptions(ocr_server_url=wrong_shape)  # type: ignore[arg-type]  # invalid on purpose

    assert "synthetic-token" not in str(error.value)


def test_liteparse_options_integer_beyond_float_range_is_checked() -> None:
    assert LiteParseBackendOptions(dpi=10**400).dpi == 10**400


@pytest.mark.parametrize("extra_options", [["quiet"], "quiet=true", {1: True}])
def test_liteparse_options_extra_options_of_the_wrong_shape_are_rejected(
    extra_options: object,
) -> None:
    with pytest.raises(ValueError, match="LiteParse extra_options must be a mapping"):
        LiteParseBackendOptions(extra_options=extra_options)  # type: ignore[arg-type]  # invalid on purpose


def test_liteparse_options_extra_option_with_its_own_setting_is_rejected() -> None:
    with pytest.raises(ValueError, match="LiteParse extra_options .*num_workers"):
        LiteParseBackendOptions(extra_options={"num_workers": 0})


def test_liteparse_options_extra_options_error_names_keys_without_values() -> None:
    with pytest.raises(ValueError) as error:
        LiteParseBackendOptions(extra_options={"password": "synthetic-secret-value"})

    assert "password" in str(error.value)
    assert "synthetic-secret-value" not in str(error.value)
