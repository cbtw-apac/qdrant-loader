"""LiteParse provider configuration."""

from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from harborrag_adapters.parsers.common.option_rules import (
    BOOLEAN,
    TEXT,
    OptionRule,
    concealed,
    integer_from,
    number_from,
    one_of,
    or_null,
    require_permitted_options,
)

MIN_NUM_WORKERS = 1
MIN_MAX_PAGES = 1
MIN_DPI = 1
OUTPUT_FORMATS = frozenset({"json", "markdown", "text"})
IMAGE_MODES = frozenset({"embed", "none", "off", "placeholder"})
INPUT_MODES = frozenset({"bytes", "path"})

_CHOICES = ("output_format", "image_mode", "input_mode")
_BLANK_IS_UNSET = ("ocr_language", "ocr_server_url", "target_pages", "tessdata_path")
_FLAGS = (
    "extract_links",
    "ocr_enabled",
    "include_raw",
    "strip_code_fences",
    "preserve_very_small_text",
    "quiet",
)
_PATH = OptionRule("a path", lambda value: isinstance(value, (str, Path)))
_OPTION_RULES: Mapping[str, OptionRule] = {
    "output_format": or_null(one_of(OUTPUT_FORMATS)),
    "image_mode": or_null(one_of(IMAGE_MODES)),
    "input_mode": one_of(INPUT_MODES),
    **{name: or_null(BOOLEAN) for name in _FLAGS},
    "ocr_language": or_null(TEXT),
    "ocr_server_url": concealed(or_null(TEXT)),
    "target_pages": or_null(TEXT),
    "tessdata_path": or_null(_PATH),
    "dpi": or_null(number_from(MIN_DPI)),
    "max_pages": or_null(integer_from(MIN_MAX_PAGES)),
    "num_workers": or_null(integer_from(MIN_NUM_WORKERS)),
}


@dataclass(slots=True)
class LiteParsePDFConfig:
    """Configuration for LlamaIndex LiteParse PDF extraction.

    A LiteParse option left as None keeps LiteParse's own default, and blank
    text counts as None. LiteParse replaces an unknown output format or image
    mode with its default and keeps a page limit of zero, so values are checked
    here before they reach it. LiteParse compares choices as written, so they
    are kept lowercase and trimmed.

    Attributes:
        output_format: LiteParse output format, one of ``OUTPUT_FORMATS``.
        image_mode: How LiteParse represents images, one of ``IMAGE_MODES``.
            LiteParse reads ``none`` as ``off``, and false also means ``off``.
        extract_links: Keep hyperlinks in the output.
        ocr_enabled: Run OCR on pages without embedded text.
        ocr_language: OCR language code.
        ocr_server_url: OCR server endpoint. Blank or None OCRs locally.
        tessdata_path: Directory holding Tesseract language data.
        max_pages: Most pages LiteParse reads from one PDF, at least
            ``MIN_MAX_PAGES``.
        target_pages: Page selection, such as ``1-3``.
        dpi: Rendering resolution for OCR, at least ``MIN_DPI``.
        preserve_very_small_text: Keep text LiteParse would drop as too small.
        password: Password for an encrypted PDF.
        quiet: Silence LiteParse's progress output.
        num_workers: Concurrent OCR workers, at least ``MIN_NUM_WORKERS``.
        input_mode: Hand LiteParse a file ``path`` or raw ``bytes``.
        include_raw: Attach LiteParse's raw result to the parse result.
        strip_code_fences: Remove the fences LiteParse puts around prose it
            reads as preformatted. Applied to its output, not passed to it.
        parser: Ready LiteParse instance to use instead of building one.
        extra_options: LiteParse constructor arguments that have no field here.
    """

    output_format: str = "markdown"
    image_mode: str = "placeholder"
    extract_links: bool = True
    ocr_enabled: bool = True
    ocr_language: str = "eng"
    ocr_server_url: str | None = None
    tessdata_path: Path | str | None = None
    max_pages: int | None = None
    target_pages: str | None = None
    dpi: int | float | None = None
    preserve_very_small_text: bool | None = None
    password: str | None = None
    quiet: bool | None = None
    num_workers: int | None = None
    input_mode: str = "path"
    include_raw: bool = False
    strip_code_fences: bool = True
    parser: Any | None = None
    extra_options: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalize written values and reject those LiteParse would misread.

        Raises:
            ValueError: An option's value is outside its permitted type, set or
                range, or ``extra_options`` repeats an option that has a field.
        """
        for name in _BLANK_IS_UNSET:
            written = getattr(self, name)
            if isinstance(written, str):
                setattr(self, name, written.strip() or None)
        for name in _CHOICES:
            setattr(self, name, _choice_as_compared(name, getattr(self, name)))
        require_permitted_options(
            "LiteParse",
            {name: getattr(self, name) for name in _OPTION_RULES},
            _OPTION_RULES,
        )
        _require_passthrough_only(self.extra_options, {item.name for item in fields(self)})


def _choice_as_compared(name: str, written: object) -> object:
    """Return a written choice the way LiteParse compares it, lowercase and trimmed.

    YAML 1.1 reads an unquoted ``off`` as false, so false means ``off`` for the
    image mode.
    """
    if written is False and name == "image_mode":
        return "off"
    if isinstance(written, str):
        return written.strip().lower()
    return written


def _require_passthrough_only(extra_options: object, own_options: set[str]) -> None:
    """Reject extra options that are no mapping or that repeat a checked option.

    The message names keys and never values, which may hold a credential.
    """
    if not isinstance(extra_options, Mapping) or not all(
        isinstance(key, str) for key in extra_options
    ):
        raise ValueError(
            "LiteParse extra_options must be a mapping with text keys, "
            f"got {type(extra_options).__name__}"
        )
    repeated = sorted(own_options.intersection(extra_options))
    if repeated:
        raise ValueError(
            "LiteParse extra_options must not repeat option(s) that have their own "
            f"setting: {', '.join(repeated)}"
        )


LiteParseBackendOptions = LiteParsePDFConfig
