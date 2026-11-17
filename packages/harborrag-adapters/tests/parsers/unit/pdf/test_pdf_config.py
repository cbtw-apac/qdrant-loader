"""PDF parser settings are checked when their configuration object is built."""

from __future__ import annotations

import re

import pytest

from harborrag_adapters.parsers.pdf.config import PDFParserConfig, PDFRouterConfig

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("min_content_chars", -1),
        ("min_content_chars", "abc"),
        ("min_content_chars", 1.5),
        ("max_pages", 0),
        ("max_pages", "abc"),
        ("max_pages", True),
    ],
)
def test_pdf_parser_config_value_outside_permitted_range_is_rejected(
    option: str,
    value: object,
) -> None:
    expected = f"PDF {option} must be .*got {re.escape(repr(value))}"

    with pytest.raises(ValueError, match=expected):
        PDFParserConfig(**{option: value})


@pytest.mark.parametrize(
    ("option", "value"),
    [("min_content_chars", 0), ("max_pages", 1), ("max_pages", None)],
)
def test_pdf_parser_config_permitted_value_is_kept(option: str, value: object) -> None:
    assert getattr(PDFParserConfig(**{option: value}), option) == value


@pytest.mark.parametrize("profile", ["nonsense", 5, ["fast"]])
def test_pdf_router_config_unknown_default_profile_is_rejected(profile: object) -> None:
    with pytest.raises(ValueError, match="Unknown default PDF profile .*: .*fast"):
        PDFRouterConfig(default_profile=profile)  # type: ignore[arg-type]  # invalid on purpose
