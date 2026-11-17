"""Image OCR engine that reads raster images with a selectable OCR library.

OCR libraries are optional, so each is imported only when an image is parsed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, ClassVar

from harborrag_adapters.parsers.common.limits import IMAGE_MAX_PIXELS
from harborrag_adapters.parsers.common.normalization import strip_code_fences
from harborrag_adapters.parsers.common.option_rules import (
    TEXT,
    OptionRule,
    concealed,
    integer_from,
    number_from,
    or_null,
    require_permitted_options,
)
from harborrag_adapters.parsers.common.resources import read_parse_input_bytes
from harborrag_adapters.parsers.common.utils import (
    get_parser_logger,
    input_label,
    parser_log_extra,
)
from harborrag_adapters.parsers.common.validation import guard_input_size
from harborrag_adapters.parsers.errors import (
    MaxPixelsExceededError,
    ParseError,
    UnreadableImageError,
)
from harborrag_adapters.parsers.image.base import HarborImageEngine
from harborrag_core.domain.element import DocumentElement
from harborrag_core.domain.parser import ParsedDocument, ParseInput

parser_logger = get_parser_logger("image")

DEFAULT_MAX_IMAGE_PIXELS = IMAGE_MAX_PIXELS

_OPTION_RULES: Mapping[str, OptionRule] = {
    "lang": or_null(TEXT),
    "config": or_null(TEXT),
    "timeout": or_null(number_from(0)),
    "max_pixels": or_null(integer_from(1)),
    "ocr_server_url": concealed(or_null(TEXT)),
}


@dataclass(slots=True)
class OcrImageEngine(HarborImageEngine):
    """Run OCR over raster images using a selectable OCR engine.

    Attributes:
        parser_name: Parser family this engine belongs to.
        parser_engine: Label naming the OCR libraries this engine can use.
        suffixes: File suffixes the engine reads.
        content_types: Media types the engine reads.
        ocr_engine: ``liteparse``, ``rapidocr`` or ``pytesseract``, in any case.
        lang: OCR language for ``liteparse`` and ``pytesseract``.
        config: Extra Tesseract arguments, for ``pytesseract`` only.
        timeout: Seconds ``pytesseract`` may run, 0 or more. None or 0 sets no
            limit.
        max_pixels: Most pixels an image may have, at least 1. None turns the
            check off.
        ocr_server_url: OCR server for ``liteparse``, which otherwise OCRs
            locally. Blank means None.
    """

    parser_name: ClassVar[str] = "image"
    parser_engine: ClassVar[str] = "rapidocr/pytesseract/liteparse"
    suffixes: ClassVar[frozenset[str]] = frozenset(
        {"png", "jpg", "jpeg", "tif", "tiff", "bmp", "gif", "webp"}
    )
    content_types: ClassVar[frozenset[str]] = frozenset(
        {
            "image/png",
            "image/jpeg",
            "image/jpg",
            "image/tiff",
            "image/bmp",
            "image/gif",
            "image/webp",
        }
    )

    ocr_engine: str = "liteparse"
    lang: str | None = None
    config: str | None = ""
    timeout: int | float | None = 60
    max_pixels: int | None = DEFAULT_MAX_IMAGE_PIXELS
    ocr_server_url: str | None = None
    _rapidocr_engine: Any | None = field(default=None, init=False, repr=False)
    _liteparse_parser: Any | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        """Normalize the OCR engine name and server URL and reject invalid options.

        A blank server URL means no OCR server, so LiteParse OCRs locally.

        Raises:
            ValueError: The OCR engine is unsupported, or an option's value is
                outside its permitted type or range.
        """
        if not isinstance(self.ocr_engine, str):
            raise ValueError("Image OCR engine must be a string")
        self.ocr_engine = self.ocr_engine.lower().strip()
        if self.ocr_engine not in {"pytesseract", "rapidocr", "liteparse"}:
            raise ValueError(
                f"Unsupported image OCR engine {self.ocr_engine!r}: "
                "pytesseract, rapidocr, liteparse"
            )
        if isinstance(self.ocr_server_url, str):
            self.ocr_server_url = self.ocr_server_url.strip() or None
        require_permitted_options(
            "Image",
            {name: getattr(self, name) for name in _OPTION_RULES},
            _OPTION_RULES,
        )

    @property
    def name(self) -> str:
        """The selected OCR engine's name."""
        return self.ocr_engine

    def parse(self, input: ParseInput) -> ParsedDocument:
        """Decode the image with Pillow, OCR it, and return extracted text."""
        parse_input = self.coerce_input(input)
        try:
            from PIL import Image
        except ImportError as exc:
            parser_logger.error(
                "Image OCR dependencies are missing for %s",
                self.ocr_engine,
                extra=parser_log_extra(
                    input=parse_input,
                    parser_name=self.parser_name,
                    parser_engine=self.ocr_engine,
                ),
            )
            raise ParseError(
                "Image OCR requires `Pillow`; install "
                "`harborrag-adapters[image]` or `pip install Pillow`."
            ) from exc

        try:
            parser_logger.debug(
                "Running OCR for %s",
                input_label(parse_input),
                extra=parser_log_extra(
                    input=parse_input,
                    parser_name=self.parser_name,
                    parser_engine=self.ocr_engine,
                    ocr_lang=self.lang,
                ),
            )
            data = guard_input_size(read_parse_input_bytes(parse_input))
            if not data:
                # 0 bytes has no image format for Pillow to identify, so
                # `Image.open()` would otherwise reject it as unreadable.
                # There is nothing to OCR, so succeed with empty output like
                # the other engines.
                return self.empty_result(
                    parse_input,
                    ocr_engine=self.ocr_engine,
                    lang=self.lang,
                )
            with Image.open(BytesIO(data)) as image:
                # Pillow's `open()` only reads the header, so the encoded size
                # guard above doesn't bound the decoded pixel buffer. Check the
                # dimensions before `.load()` actually decodes the image, since
                # a small, highly-compressed file can still expand to an
                # enormous in-memory bitmap.
                width, height = image.size
                pixel_count = width * height
                if self.max_pixels is not None and pixel_count > self.max_pixels:
                    raise MaxPixelsExceededError(
                        width=width,
                        height=height,
                        max_pixels=self.max_pixels,
                        filename=parse_input.filename,
                    )
                image.load()
                # OCR providers use several no-detection sentinels across
                # versions (``None``, an empty result object, or whitespace).
                # They all mean a successful parse with no extracted text.
                content = (self._extract_text(data, image) or "").strip()
        except ParseError:
            raise
        except Image.UnidentifiedImageError as exc:
            # Pillow's own message is a raw `<_io.BytesIO object at 0x...>`
            # repr with no detail about the file, so it gets replaced (not
            # wrapped) with one naming the file and its size.
            parser_logger.warning(
                "Image OCR failed for %s: unreadable image (%d bytes)",
                input_label(parse_input),
                len(data),
                extra=parser_log_extra(
                    input=parse_input,
                    parser_name=self.parser_name,
                    parser_engine=self.ocr_engine,
                    ocr_lang=self.lang,
                ),
            )
            raise UnreadableImageError(filename=parse_input.filename, size_bytes=len(data)) from exc
        except Image.DecompressionBombError as exc:
            # Past twice Pillow's `MAX_IMAGE_PIXELS` (~179M pixels by default)
            # `Image.open()` raises before the dimension check above runs.
            # `DecompressionBombError` subclasses `Exception`, not `OSError`,
            # so it needs its own clause or it escapes untyped. Read the
            # ceiling now, not at import: deployments may tune it.
            parser_logger.warning(
                "Image OCR failed for %s: %s",
                input_label(parse_input),
                exc,
                extra=parser_log_extra(
                    input=parse_input,
                    parser_name=self.parser_name,
                    parser_engine=self.ocr_engine,
                    ocr_lang=self.lang,
                ),
            )
            ceiling = 2 * (Image.MAX_IMAGE_PIXELS or 0)
            if self.max_pixels is not None and self.max_pixels <= ceiling:
                raise MaxPixelsExceededError(
                    more_than=ceiling,
                    max_pixels=self.max_pixels,
                    filename=parse_input.filename,
                ) from exc
            # The image may still be within a `max_pixels` set above the
            # ceiling, so name the ceiling as what rejected it.
            capped = (
                f" Pillow's decompression-bomb ceiling ({ceiling} pixels) is below "
                f"the configured max_pixels {self.max_pixels}."
                if self.max_pixels is not None
                else ""
            )
            raise ParseError(f"Image OCR failed: {exc}{capped}") from exc
        except (RuntimeError, OSError, ValueError) as exc:
            parser_logger.warning(
                "Image OCR failed for %s: %s",
                input_label(parse_input),
                exc,
                extra=parser_log_extra(
                    input=parse_input,
                    parser_name=self.parser_name,
                    parser_engine=self.ocr_engine,
                    ocr_lang=self.lang,
                ),
            )
            raise ParseError(f"Image OCR failed: {exc}") from exc

        elements = (
            [
                DocumentElement(
                    id="image:ocr:0",
                    type="image",
                    content=content,
                    metadata={"filename": parse_input.filename},
                )
            ]
            if content
            else []
        )
        parser_logger.info(
            "Parsed image OCR %s engine=%s content_chars=%d elements=%d",
            input_label(parse_input),
            self.ocr_engine,
            len(content),
            len(elements),
            extra=parser_log_extra(
                input=parse_input,
                parser_name=self.parser_name,
                parser_engine=self.ocr_engine,
                ocr_lang=self.lang,
                content_chars=len(content),
                elements=len(elements),
            ),
        )
        return ParsedDocument(
            content=content,
            elements=elements,
            parser_name=self.parser_name,
            parser_version=self.parser_version,
            metadata=self.metadata_for(
                parse_input,
                ocr_engine=self.ocr_engine,
                lang=self.lang,
            ),
        )

    def _extract_text(self, data: bytes, image: Any) -> str:
        """Dispatch OCR while keeping optional dependencies lazy."""
        if self.ocr_engine == "liteparse":
            return self._extract_with_liteparse(data)
        if self.ocr_engine == "rapidocr":
            data = self._prepare_rapidocr_bytes(data, image)
            return self._extract_with_rapidocr(data)
        return self._extract_with_pytesseract(image)

    def _prepare_rapidocr_bytes(self, data: bytes, image: Any) -> bytes:
        """Convert image modes RapidOCR misreads to RGB before detection.

        RapidOCR is sensitive to CMYK and similar non-RGB modes, where scans
        and print images otherwise give a misleading empty detection result.
        """
        mode = getattr(image, "mode", "")
        if mode.upper() in {"CMYK", "YCBCR", "YCbCr", "RGBA", "LA", "P"}:
            rgb_image = image.convert("RGB")
            buffer = BytesIO()
            rgb_image.save(buffer, format="PNG")
            return buffer.getvalue()
        return data

    def _extract_with_pytesseract(self, image: Any) -> str:
        """Extract text with the legacy Tesseract adapter."""
        try:
            import pytesseract
        except ImportError as exc:
            raise ParseError(
                "Image OCR with pytesseract requires `pytesseract`; install "
                "`harborrag-adapters[image-tesseract]` or `pip install pytesseract`."
            ) from exc

        try:
            content = pytesseract.image_to_string(
                image,
                lang=self.lang,
                config=self.config or "",
                timeout=self.timeout,
            )
        except pytesseract.TesseractError as exc:
            # Tesseract exits non-zero both for genuine failures (missing
            # language data, corrupt image) and for the documented "no text
            # detected" case, which it signals with this specific message.
            # Only that signal means a successful parse with empty output;
            # every other TesseractError still surfaces as a failure.
            if "empty page" in str(exc).lower():
                return ""
            raise
        return "" if content is None else str(content).strip()

    def _extract_with_liteparse(self, data: bytes) -> str:
        """Extract text by sending the image to the shared OCR server.

        LiteParse accepts raster bytes directly, so images use the same OCR
        service as scanned PDFs instead of a second local inference runtime.
        The parser is memoized because constructing it is not free, and no
        ``dpi`` is passed: that setting rasterizes PDF pages and an image is
        already at its native resolution.
        """
        if self._liteparse_parser is None:
            try:
                from liteparse import LiteParse
            except ImportError as exc:
                raise ParseError(
                    "Image OCR with LiteParse requires the `liteparse` package; "
                    "install `harborrag-adapters[pdf-liteparse]`."
                ) from exc
            options: dict[str, Any] = {"ocr_enabled": True, "quiet": True}
            if self.lang:
                options["ocr_language"] = self.lang
            if self.ocr_server_url:
                options["ocr_server_url"] = self.ocr_server_url
            self._liteparse_parser = LiteParse(**options)

        result = self._liteparse_parser.parse(data)
        # An OCR'd image is a single unstructured block, which LiteParse's
        # Markdown writer readily fences as preformatted text.
        return strip_code_fences(str(getattr(result, "text", "") or ""))

    def _extract_with_rapidocr(self, data: bytes) -> str:
        """Extract ordered text lines with a memoized RapidOCR engine."""
        if self._rapidocr_engine is None:
            try:
                from rapidocr import RapidOCR
            except ImportError as exc:
                raise ParseError(
                    "Image OCR with RapidOCR requires `rapidocr` and an inference "
                    "runtime; install `harborrag-adapters[image-rapidocr]`."
                ) from exc
            self._rapidocr_engine = RapidOCR()

        result = self._rapidocr_engine(data)
        texts = getattr(result, "txts", None) or ()
        return "\n".join(text for value in texts if (text := str(value).strip()))


ImageParser = OcrImageEngine
