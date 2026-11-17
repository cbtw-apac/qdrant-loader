"""LiteParse provider configuration."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MIN_NUM_WORKERS = 1


@dataclass(slots=True)
class LiteParsePDFConfig:
    """Configuration for LlamaIndex LiteParse PDF extraction.

    A field left as None keeps LiteParse's own default.

    Attributes:
        output_format: LiteParse output format, such as ``markdown``.
        image_mode: How LiteParse represents images in its output.
        extract_links: Keep hyperlinks in the output.
        ocr_enabled: Run OCR on pages without embedded text.
        ocr_language: OCR language code.
        ocr_server_url: OCR server endpoint; blank or None OCRs locally.
        tessdata_path: Directory holding Tesseract language data.
        max_pages: Most pages LiteParse reads from one PDF.
        target_pages: Page selection, such as ``1-3``.
        dpi: Rendering resolution for OCR.
        preserve_very_small_text: Keep text LiteParse would drop as too small.
        password: Password for an encrypted PDF.
        quiet: Silence LiteParse's progress output.
        num_workers: Concurrent OCR workers, at least ``MIN_NUM_WORKERS``.
        input_mode: Hand LiteParse a file ``path`` or raw ``bytes``.
        include_raw: Attach LiteParse's raw result to the parse result.
        strip_code_fences: Remove the fences LiteParse puts around prose it
            reads as preformatted. Applied to its output, not passed to it.
        parser: Ready LiteParse instance to use instead of building one.
        extra_options: Further LiteParse constructor arguments.
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
        """Treat a blank OCR server URL as unset and reject an invalid worker count.

        Raises:
            ValueError: ``num_workers`` is set but is not an integer of at
                least ``MIN_NUM_WORKERS``.
        """
        if isinstance(self.ocr_server_url, str):
            self.ocr_server_url = self.ocr_server_url.strip() or None
        if self.num_workers is not None and not _is_worker_count(self.num_workers):
            raise ValueError(
                f"LiteParse num_workers must be an integer of at least "
                f"{MIN_NUM_WORKERS}, got {self.num_workers!r}"
            )


def _is_worker_count(value: object) -> bool:
    """Tell whether a value is a usable worker count, which a boolean is not."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= MIN_NUM_WORKERS


LiteParseBackendOptions = LiteParsePDFConfig
