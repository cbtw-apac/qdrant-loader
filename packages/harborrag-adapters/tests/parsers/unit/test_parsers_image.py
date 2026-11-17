from __future__ import annotations

import io
import logging
import re
import sys
from types import SimpleNamespace

import pytest
from PIL import Image

from harborrag_adapters.parsers.compat import ImageParser
from harborrag_adapters.parsers.errors import MaxPixelsExceededError, ParseError
from harborrag_core.domain.parser import ParseInput

pytestmark = [pytest.mark.unit, pytest.mark.whitebox]


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (10, 10), color="white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_rapidocr_extracts_ordered_lines_and_reuses_engine(monkeypatch) -> None:
    created: list[object] = []

    class _RapidOCR:
        def __init__(self) -> None:
            created.append(self)

        def __call__(self, _content: bytes) -> object:
            return SimpleNamespace(txts=(" first line ", "", "second line"))

    monkeypatch.setitem(sys.modules, "rapidocr", SimpleNamespace(RapidOCR=_RapidOCR))
    parser = ImageParser(ocr_engine="RAPIDOCR")
    parse_input = ParseInput(content=_png_bytes(), filename="scan.png")

    first = parser.parse(parse_input)
    second = parser.parse(parse_input)

    assert first.content == "first line\nsecond line"
    assert first.metadata["ocr_engine"] == "rapidocr"
    assert second.content == first.content
    assert created == [parser._rapidocr_engine]


def test_rapidocr_converts_cmyk_to_rgb_before_ocr(monkeypatch) -> None:
    seen: dict[str, str] = {}

    class _RapidOCR:
        def __call__(self, content: bytes) -> object:
            seen["mode"] = Image.open(io.BytesIO(content)).mode
            return SimpleNamespace(txts=("cmyk text",))

    monkeypatch.setitem(sys.modules, "rapidocr", SimpleNamespace(RapidOCR=_RapidOCR))
    buffer = io.BytesIO()
    Image.new("CMYK", (10, 10), color=(0, 0, 0, 0)).save(buffer, format="JPEG")

    document = ImageParser(ocr_engine="rapidocr").parse(
        ParseInput(content=buffer.getvalue(), filename="cmyk.jpg")
    )

    assert document.content == "cmyk text"
    assert seen["mode"] == "RGB"


def test_image_parser_rejects_unknown_ocr_engine() -> None:
    with pytest.raises(ValueError, match="Unsupported image OCR engine"):
        ImageParser(ocr_engine="unknown")


def test_image_parser_treats_no_ocr_text_as_empty_success(monkeypatch, caplog) -> None:
    monkeypatch.setattr(ImageParser, "_extract_text", lambda *_args: None)

    with caplog.at_level(logging.INFO, logger="harborrag.adapters.parsers.image"):
        document = ImageParser().parse(ParseInput(content=_png_bytes(), filename="blank.png"))

    assert document.content == ""
    assert document.elements == []
    assert "Parsed image OCR blank.png" in caplog.text
    assert "content_chars=0 elements=0" in caplog.text


class _TesseractError(RuntimeError):
    """Stand-in for `pytesseract.TesseractError` (status + message)."""

    def __init__(self, status: int, message: str) -> None:
        self.status = status
        self.message = message
        super().__init__(message)


def test_pytesseract_treats_empty_page_as_empty_success(monkeypatch) -> None:
    """Treat Tesseract's "Empty page!!" exit as a successful empty parse.

    Tesseract exits non-zero with that message when a page has no detectable
    text. That used to be indistinguishable from a genuine failure and was
    rewrapped as a `ParseError` instead of the empty-success path every other
    OCR engine (and this one, for a `None`/empty return) takes.
    """

    def _raise_empty_page(*_args: object, **_kwargs: object) -> str:
        raise _TesseractError(1, "Empty page!!\nWARNING: Invalid resolution 0 dpi.\n")

    monkeypatch.setitem(
        sys.modules,
        "pytesseract",
        SimpleNamespace(image_to_string=_raise_empty_page, TesseractError=_TesseractError),
    )

    document = ImageParser(ocr_engine="pytesseract").parse(
        ParseInput(content=_png_bytes(), filename="blank_scan.png")
    )

    assert document.content == ""
    assert document.elements == []


def test_pytesseract_other_tesseract_errors_still_raise(monkeypatch) -> None:
    """Keep a genuine Tesseract failure surfacing as a typed `ParseError`.

    Only the "no text found" signal is an empty success.
    """

    def _raise_real_failure(*_args: object, **_kwargs: object) -> str:
        raise _TesseractError(1, "Error opening data file eng.traineddata")

    monkeypatch.setitem(
        sys.modules,
        "pytesseract",
        SimpleNamespace(image_to_string=_raise_real_failure, TesseractError=_TesseractError),
    )

    with pytest.raises(ParseError, match="Image OCR failed"):
        ImageParser(ocr_engine="pytesseract").parse(
            ParseInput(content=_png_bytes(), filename="scan.png")
        )


def test_image_parser_raises_typed_error_instead_of_crashing_on_decompression_bomb(
    monkeypatch,
) -> None:
    """Report Pillow's decompression-bomb refusal as a typed `ParseError`.

    `Image.open()` runs its own pixel-count guard against Pillow's global
    `MAX_IMAGE_PIXELS` before our own `max_pixels` check gets a chance to run,
    raising `DecompressionBombError` (a bare `Exception`, not `OSError`). That
    used to escape uncaught.
    """
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10)

    with pytest.raises(ParseError, match="Image OCR failed"):
        ImageParser().parse(ParseInput(content=_png_bytes(), filename="huge.png"))


def test_image_parser_reports_unreadable_image_with_filename_and_size_not_raw_bytesio_repr() -> (
    None
):
    """Name the file and its size when Pillow cannot identify the image.

    Bytes Pillow cannot identify as any supported format (corrupt, truncated,
    or not actually an image) used to surface as a raw `UnidentifiedImageError:
    cannot identify image file <_io.BytesIO object at 0x...>`, unreadable on
    its own, with no clue which file failed.
    """
    garbage = b"not an image, just plain bytes"

    with pytest.raises(ParseError) as exc_info:
        ImageParser().parse(ParseInput(content=garbage, filename="quarterly_report.png"))

    message = str(exc_info.value)
    assert "quarterly_report.png" in message
    assert str(len(garbage)) in message
    assert "_io.BytesIO" not in message


def test_image_parser_rejects_image_over_configured_max_pixels_with_clear_error() -> None:
    """Reject an image over the configured `max_pixels`, naming size and limit.

    The image is real and well formed, and it stays under Pillow's own default
    decompression-bomb threshold, so `Image.open()` decodes the header fine.
    It must not be left to fail later as a bare `UnidentifiedImageError`.
    """
    width, height = 1000, 1001
    buffer = io.BytesIO()
    Image.new("L", (width, height), color=128).save(buffer, format="PNG")
    parser = ImageParser(max_pixels=1_000_000)

    with pytest.raises(
        ParseError,
        match=r"Image 1000x1001 \(1001000 pixels\) exceeds max_pixels 1000000",
    ):
        parser.parse(
            ParseInput(content=buffer.getvalue(), filename="dashboard_export_over_limit.png")
        )


def test_image_past_pillows_bomb_ceiling_reports_the_configured_max_pixels(monkeypatch) -> None:
    """Name the configured `max_pixels` when it sits below Pillow's ceiling.

    Above twice Pillow's `MAX_IMAGE_PIXELS` (~179M pixels by default),
    `Image.open()` raises before our own dimension check runs. When the
    configured `max_pixels` sits below that ceiling the image certainly
    breaks it, so the error must name the configured limit, not Pillow's.
    """
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10)  # ceiling: 20 pixels

    with pytest.raises(MaxPixelsExceededError, match=r"exceeds max_pixels 15\b") as exc_info:
        ImageParser(max_pixels=15).parse(
            ParseInput(content=_png_bytes(), filename="dashboard_export_over_limit.png")
        )

    assert exc_info.value.max_pixels == 15
    assert "dashboard_export_over_limit.png" in str(exc_info.value)


def test_image_past_pillows_bomb_ceiling_names_the_ceiling_capping_max_pixels(
    monkeypatch,
) -> None:
    """Say Pillow's ceiling rejected the image when `max_pixels` is above it.

    A configured `max_pixels` above Pillow's ceiling cannot be honored, and
    the image may still be within it, so the error must not claim a
    `max_pixels` breach.
    """
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10)  # ceiling: 20 pixels

    with pytest.raises(ParseError) as exc_info:
        ImageParser(max_pixels=1_000).parse(ParseInput(content=_png_bytes(), filename="huge.png"))

    assert not isinstance(exc_info.value, MaxPixelsExceededError)
    assert "decompression-bomb ceiling (20 pixels) is below the configured max_pixels 1000" in str(
        exc_info.value
    )


def test_liteparse_sends_image_bytes_to_the_ocr_server_and_reuses_the_parser(monkeypatch) -> None:
    built: list[dict[str, object]] = []
    seen: list[bytes] = []

    class _LiteParse:
        def __init__(self, **options: object) -> None:
            built.append(options)

        def parse(self, data: bytes) -> object:
            seen.append(data)
            return SimpleNamespace(text=" extracted text ")

    monkeypatch.setitem(sys.modules, "liteparse", SimpleNamespace(LiteParse=_LiteParse))
    parser = ImageParser(
        ocr_engine="LiteParse",
        lang="en",
        ocr_server_url="http://ppocr-server:8888/ocr",
    )
    parse_input = ParseInput(content=_png_bytes(), filename="scan.png")

    first = parser.parse(parse_input)
    second = parser.parse(parse_input)

    assert first.content == "extracted text"
    assert second.content == "extracted text"
    assert first.metadata["ocr_engine"] == "liteparse"
    # Constructing LiteParse is not free, so it is memoized across images.
    assert len(built) == 1
    assert built[0]["ocr_server_url"] == "http://ppocr-server:8888/ocr"
    assert built[0]["ocr_language"] == "en"
    # `dpi` rasterizes PDF pages; an image already has a native resolution.
    assert "dpi" not in built[0]
    assert seen[0] == _png_bytes()


def test_liteparse_image_engine_reports_a_missing_package(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "liteparse", None)
    parser = ImageParser(ocr_engine="liteparse")

    with pytest.raises(ParseError, match="pdf-liteparse"):
        parser.parse(ParseInput(content=_png_bytes(), filename="scan.png"))


def test_image_engine_rejects_an_unknown_ocr_engine() -> None:
    with pytest.raises(ValueError, match="pytesseract, rapidocr, liteparse"):
        ImageParser(ocr_engine="nonexistent")


def test_liteparse_image_engine_strips_spurious_code_fences(monkeypatch) -> None:
    class _LiteParse:
        def __init__(self, **_options: object) -> None: ...

        def parse(self, _data: bytes) -> object:
            return SimpleNamespace(text="```python\nscanned prose\n```")

    monkeypatch.setitem(sys.modules, "liteparse", SimpleNamespace(LiteParse=_LiteParse))
    parser = ImageParser(ocr_engine="liteparse")

    result = parser.parse(ParseInput(content=_png_bytes(), filename="scan.png"))

    assert result.content == "scanned prose"


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("timeout", "abc"),
        ("timeout", -1),
        ("timeout", True),
        ("lang", 5),
        ("config", 5),
        ("max_pixels", 0),
        ("max_pixels", 2.5),
    ],
)
def test_image_parser_option_value_outside_permitted_set_is_rejected(
    option: str,
    value: object,
) -> None:
    expected = f"Image {option} must be .*got {re.escape(repr(value))}"

    with pytest.raises(ValueError, match=expected):
        ImageParser(**{option: value})


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("timeout", None),
        ("timeout", 0),
        ("timeout", 2.5),
        ("lang", None),
        ("lang", "en"),
        ("config", "--psm 6"),
        ("config", None),
        ("max_pixels", None),
        ("timeout", 10**400),
    ],
)
def test_image_parser_permitted_option_value_is_kept(option: str, value: object) -> None:
    assert getattr(ImageParser(**{option: value}), option) == value


def test_image_parser_rejected_ocr_server_url_is_not_shown() -> None:
    wrong_shape = ["https://reader:synthetic-token@ocr.example.test/ocr"]

    with pytest.raises(ValueError, match="Image ocr_server_url must be .*got list") as error:
        ImageParser(ocr_server_url=wrong_shape)

    assert "synthetic-token" not in str(error.value)
