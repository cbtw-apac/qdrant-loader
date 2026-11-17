"""Profiles and policy configuration for PDF engine routing."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from harborrag_adapters.parsers.common.limits import PDF_MAX_PAGES
from harborrag_adapters.parsers.common.option_rules import (
    integer_from,
    or_null,
    require_permitted_options,
)

MIN_MAX_PAGES = 1
_PARSER_OPTION_RULES = {
    "min_content_chars": integer_from(0),
    "max_pages": or_null(integer_from(MIN_MAX_PAGES)),
}


class PDFParserProfile(StrEnum):
    """Named PDF engine orderings for cost and quality tradeoffs."""

    LITEPARSE = "liteparse"
    FAST = "fast"
    BALANCED = "balanced"
    OCR = "ocr"
    OCR_FIRST = "ocr_first"
    QUALITY = "quality"
    SCIENTIFIC = "scientific"

    @classmethod
    def normalize(cls, value: PDFParserProfile | str) -> PDFParserProfile:
        """Return the profile a name refers to, ignoring case and outer spaces.

        Args:
            value: A profile or its name.

        Returns:
            The matching profile.

        Raises:
            ValueError: No profile has this name.
        """
        if isinstance(value, cls):
            return value
        normalized = str(value).lower().strip()
        try:
            return cls(normalized)
        except ValueError as error:
            supported = ", ".join(profile.value for profile in cls)
            raise ValueError(f"Unknown PDF parser profile {value!r}: {supported}") from error


@dataclass(frozen=True, slots=True)
class PDFProfileConfig:
    """Engine order and acceptance policy for one PDF parsing profile.

    Attributes:
        engine_order: PDF engine names, tried first to last.
        minimum_quality_score: Lowest quality score that accepts an engine's
            result, from 0 to 1.
        preserve_equations: Marks a profile meant to keep equations. No code
            reads it.
        preserve_tables: Marks a profile meant to keep tables. No code reads it.
        preserve_layout: Marks a profile meant to keep page layout. No code
            reads it.
    """

    engine_order: tuple[str, ...]
    minimum_quality_score: float
    preserve_equations: bool = False
    preserve_tables: bool = False
    preserve_layout: bool = False

    def __post_init__(self) -> None:
        """Reject a quality score outside 0 to 1.

        Raises:
            ValueError: ``minimum_quality_score`` is below 0 or above 1.
        """
        if not 0 <= self.minimum_quality_score <= 1:
            raise ValueError("PDF minimum_quality_score must be between 0 and 1")


def default_pdf_profiles() -> dict[str, PDFProfileConfig]:
    """Return the built-in profiles by name.

    The default ``liteparse`` profile reads layout-aware text with OCR for
    scanned pages, and falls back to PyMuPDF when LiteParse is unavailable.
    """
    return {
        "liteparse": PDFProfileConfig(("liteparse", "pymupdf"), 0.65),
        "fast": PDFProfileConfig(("pymupdf", "liteparse"), 0.65),
        "balanced": PDFProfileConfig(
            ("pymupdf", "docling", "liteparse", "mineru", "paddleocr"),
            0.80,
        ),
        "ocr": PDFProfileConfig(
            ("docling", "mineru", "paddleocr", "pymupdf"),
            0.75,
            preserve_tables=True,
            preserve_layout=True,
        ),
        "ocr_first": PDFProfileConfig(
            ("paddleocr", "mineru", "docling", "pymupdf"),
            0.75,
            preserve_tables=True,
            preserve_layout=True,
        ),
        "quality": PDFProfileConfig(
            ("docling", "mineru", "paddleocr", "pymupdf", "liteparse"),
            0.85,
            preserve_equations=True,
            preserve_tables=True,
            preserve_layout=True,
        ),
        "scientific": PDFProfileConfig(
            ("mineru", "docling", "pymupdf"),
            0.85,
            preserve_equations=True,
            preserve_tables=True,
            preserve_layout=True,
        ),
    }


@dataclass(frozen=True, slots=True)
class PDFRouterConfig:
    """Default profile and named engine-order policies.

    Attributes:
        default_profile: Name of the profile used when a request names none.
        profiles: Engine-order policies by profile name.
    """

    default_profile: str = "liteparse"
    profiles: dict[str, PDFProfileConfig] = field(default_factory=default_pdf_profiles)

    def __post_init__(self) -> None:
        """Reject a default profile that names none of the profiles.

        Raises:
            ValueError: ``default_profile`` is not a key of ``profiles``.
        """
        if not isinstance(self.default_profile, str) or self.default_profile not in self.profiles:
            raise ValueError(
                f"Unknown default PDF profile {self.default_profile!r}: {', '.join(self.profiles)}"
            )


@dataclass(frozen=True, slots=True)
class PDFParserConfig:
    """PDF parser quality threshold, page limit and routing profiles.

    Attributes:
        min_content_chars: Fewest extracted characters that accept a result,
            0 or more.
        max_pages: Most pages a PDF may have, at least ``MIN_MAX_PAGES``. None
            turns the check off.
        router: The profiles and the default one.
    """

    min_content_chars: int = 20
    max_pages: int | None = PDF_MAX_PAGES
    router: PDFRouterConfig = field(default_factory=PDFRouterConfig)

    def __post_init__(self) -> None:
        """Reject a quality threshold or page limit outside its range.

        Raises:
            ValueError: ``min_content_chars`` is not a non-negative integer, or
                ``max_pages`` is neither None nor an integer of at least
                ``MIN_MAX_PAGES``.
        """
        require_permitted_options(
            "PDF",
            {"min_content_chars": self.min_content_chars, "max_pages": self.max_pages},
            _PARSER_OPTION_RULES,
        )


PdfParserProfile = PDFParserProfile
