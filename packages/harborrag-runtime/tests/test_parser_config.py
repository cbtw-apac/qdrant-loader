from __future__ import annotations

import logging
from pathlib import Path
from textwrap import dedent

import pytest

from harborrag_adapters.parsers import HarborParserFactory, HarborParserRegistry
from harborrag_adapters.parsers.common.family import HarborSingleEngineFamilyParser
from harborrag_adapters.parsers.compat import (
    DoclingBackend,
    LiteParseBackend,
    MinerUBackend,
    PdfParser,
    PdfParserProfile,
    PyMuPdfBackend,
)
from harborrag_adapters.parsers.image.parser import HarborImageParser
from harborrag_runtime.config import (
    ParserConfigurationError,
    load_parser_catalog,
)
from harborrag_runtime.config.parsers.providers import supported_parser_names
from harborrag_runtime.config.parsers.schemas import (
    ParserDefinition,
    PdfBackendDefinition,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]


def _write_config(tmp_path: Path, content: str) -> Path:
    config_path = tmp_path / "parsers.yaml"
    config_path.write_text(dedent(content), encoding="utf-8")
    return config_path


def test_repository_config_builds_enabled_parser_overrides(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HARBORRAG_OCR_SERVER_URL", raising=False)
    with caplog.at_level(logging.INFO, logger="harborrag.runtime.config.parsers"):
        catalog = load_parser_catalog(REPO_ROOT / "config" / "ingestion" / "parsers.yaml")

    assert catalog.names(enabled_only=True) == ["image-liteparse", "pdf-liteparse"]

    pdf_parser = catalog.build("pdf-liteparse")
    assert isinstance(pdf_parser, PdfParser)
    assert [backend.name for backend in pdf_parser.backends] == ["liteparse"]
    assert isinstance(pdf_parser.backends[0], LiteParseBackend)
    assert pdf_parser.backends[0].options.ocr_server_url is None, (
        "without HARBORRAG_OCR_SERVER_URL LiteParse OCRs locally"
    )

    image_parser = catalog.build("image-liteparse")
    assert isinstance(image_parser, HarborImageParser)
    assert image_parser.ocr_engine == "liteparse"
    assert image_parser.engines[0].ocr_server_url is None

    harbor_parser = catalog.build_harbor_parser()
    attachment_parser = catalog.build_harbor_parser()
    assert isinstance(harbor_parser.create("pdf"), PdfParser)
    assert attachment_parser is not harbor_parser
    assert isinstance(harbor_parser.create("image"), HarborImageParser)
    assert harbor_parser.resolve("README.md", "text/markdown") is not None
    assert "Parser catalog loaded" in caplog.text
    assert "definitions=2 enabled=2" in caplog.text


def test_repository_config_keeps_inactive_alternatives_commented() -> None:
    catalog = load_parser_catalog(REPO_ROOT / "config" / "ingestion" / "parsers.yaml")

    assert catalog.names() == ["image-liteparse", "pdf-liteparse"]


def test_ocr_server_url_follows_the_environment_over_the_catalog_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HARBORRAG_OCR_SERVER_URL", "http://localhost:8888/ocr")

    catalog = load_parser_catalog(REPO_ROOT / "config" / "ingestion" / "parsers.yaml")

    assert catalog.build("pdf-liteparse").backends[0].options.ocr_server_url == (
        "http://localhost:8888/ocr"
    )
    assert catalog.build("image-liteparse").engines[0].ocr_server_url == (
        "http://localhost:8888/ocr"
    )


def test_an_empty_ocr_server_url_means_no_ocr_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARBORRAG_OCR_SERVER_URL", "  ")

    catalog = load_parser_catalog(REPO_ROOT / "config" / "ingestion" / "parsers.yaml")

    liteparse = catalog.build("pdf-liteparse").backends[0]
    assert liteparse.options.ocr_server_url is None
    assert "ocr_server_url" not in liteparse._constructor_kwargs()
    assert catalog.build("image-liteparse").engines[0].ocr_server_url is None


def test_setting_reference_to_an_unset_variable_without_a_default_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TEST_OCR_SERVER_URL", raising=False)
    config_path = _write_config(
        tmp_path,
        """
        version: 1
        parsers:
          custom-image:
            parser: image
            settings:
              ocr_engine: liteparse
              ocr_server_url: ${TEST_OCR_SERVER_URL}
        """,
    )

    with pytest.raises(ParserConfigurationError, match="TEST_OCR_SERVER_URL"):
        load_parser_catalog(config_path)


def test_builds_explicit_pdf_backend_order_and_options(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        """
        version: 1
        parsers:
          custom-pdf:
            parser: pdf
            settings:
              min_content_chars: 40
            engines:
              - backend: pymupdf
              - backend: docling
                settings:
                  do_ocr: true
                  force_full_page_ocr: true
        """,
    )

    parser = load_parser_catalog(config_path).build("custom-pdf")

    assert isinstance(parser, PdfParser)
    assert parser.min_content_chars == 40
    assert [backend.name for backend in parser.backends] == ["pymupdf", "docling"]
    assert isinstance(parser.backends[0], PyMuPdfBackend)
    assert isinstance(parser.backends[1], DoclingBackend)
    assert parser.backends[1].options.force_full_page_ocr is True


def test_build_allows_explicit_code_overrides(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        """
        version: 1
        parsers:
          fast-pdf:
            parser: pdf
            settings:
              profile: fast
              min_content_chars: 20
        """,
    )
    catalog = load_parser_catalog(config_path)

    parser = catalog.build("fast-pdf", overrides={"min_content_chars": 100})

    assert isinstance(parser, PdfParser)
    assert parser.profile == PdfParserProfile.FAST
    assert parser.min_content_chars == 100


def test_backend_secrets_and_subprocess_environment_resolve_from_environment(
    tmp_path: Path,
) -> None:
    config_path = _write_config(
        tmp_path,
        """
        version: 1
        parsers:
          protected-pdf:
            parser: pdf
            engines:
              - backend: liteparse
                secrets:
                  password_env: TEST_PDF_PASSWORD
              - backend: mineru
                settings:
                  backend: vlm-http-client
                  server_url: https://vlm.example.test/v1
                environment:
                  MINERU_VL_API_KEY: TEST_OPENAI_API_KEY
                  MINERU_VL_MODEL_NAME: TEST_OPENAI_VLM_MODEL
        """,
    )

    parser = load_parser_catalog(config_path).build(
        "protected-pdf",
        environment={
            "TEST_PDF_PASSWORD": "pdf-secret",
            "TEST_OPENAI_API_KEY": "api-secret",
            "TEST_OPENAI_VLM_MODEL": "document-vlm",
        },
    )

    assert isinstance(parser, PdfParser)
    assert isinstance(parser.backends[0], LiteParseBackend)
    assert parser.backends[0].options.password == "pdf-secret"
    assert isinstance(parser.backends[1], MinerUBackend)
    assert parser.backends[1].options.server_url == "https://vlm.example.test/v1"
    assert parser.backends[1].options.env == {
        "MINERU_VL_API_KEY": "api-secret",
        "MINERU_VL_MODEL_NAME": "document-vlm",
    }


def test_missing_backend_environment_reference_fails_at_build(tmp_path: Path) -> None:
    config_path = _write_config(
        tmp_path,
        """
        version: 1
        parsers:
          protected-pdf:
            parser: pdf
            engines:
              - backend: liteparse
                secrets:
                  password_env: TEST_PDF_PASSWORD
        """,
    )
    catalog = load_parser_catalog(config_path)

    with pytest.raises(ParserConfigurationError, match="TEST_PDF_PASSWORD"):
        catalog.build("protected-pdf", environment={})


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("parsers: {}", "version must be 1"),
        ("version: 2\nparsers: {}", "Unsupported parser configuration version"),
        (
            """
            version: 1
            parsers:
              broken:
                parser: unknown
            """,
            "unsupported parser",
        ),
        (
            """
            version: 1
            parsers:
              broken:
                parser: markdown
                settings:
                  profile: fast
            """,
            "unknown markdown setting",
        ),
        (
            """
            version: 1
            parsers:
              broken:
                parser: markdown
                engines:
                  - backend: pymupdf
            """,
            "engines only when parser is 'pdf'",
        ),
        (
            """
            version: 1
            parsers:
              broken:
                parser: pdf
                engines:
                  - backend: unknown
            """,
            "unsupported PDF backend",
        ),
        (
            """
            version: 1
            parsers:
              broken:
                parser: pdf
                engines:
                  - backend: pymupdf
                    settings:
                      unknown: true
            """,
            "unknown pymupdf setting",
        ),
        (
            """
            version: 1
            parsers:
              broken:
                parser: pdf
                settings:
                  profile: quality
                engines:
                  - backend: pymupdf
            """,
            "cannot combine",
        ),
        (
            """
            version: 1
            parsers:
              broken:
                parser: pdf
                engines:
                  - backend: liteparse
                    settings:
                      password: secret
            """,
            "cannot store secret",
        ),
        (
            """
            version: 1
            parsers:
              broken:
                parser: pdf
                engines:
                  - backend: docling
                    environment:
                      OPENAI_API_KEY: OPENAI_API_KEY
            """,
            "supported only for the MinerU",
        ),
    ],
)
def test_rejects_invalid_parser_configuration(
    tmp_path: Path,
    content: str,
    message: str,
) -> None:
    with pytest.raises(ParserConfigurationError, match=message):
        load_parser_catalog(_write_config(tmp_path, content))


def test_parser_definition_repr_hides_settings() -> None:
    definition = ParserDefinition(
        name="secretive",
        parser="pdf",
        settings={"api_key": "super-secret-value"},
    )

    representation = repr(definition)

    assert "super-secret-value" not in representation
    assert "secretive" in representation


def test_pdf_backend_definition_repr_hides_settings() -> None:
    backend = PdfBackendDefinition(
        backend="mineru",
        settings={"server_url": "https://secret.internal/v1"},
    )

    representation = repr(backend)

    assert "https://secret.internal/v1" not in representation
    assert "mineru" in representation


def test_registry_rejects_multiple_enabled_profiles_for_same_parser(
    tmp_path: Path,
) -> None:
    config_path = _write_config(
        tmp_path,
        """
        version: 1
        parsers:
          fast:
            parser: pdf
            settings:
              profile: fast
          quality:
            parser: pdf
            settings:
              profile: quality
        """,
    )
    catalog = load_parser_catalog(config_path)

    with pytest.raises(ParserConfigurationError, match="both configure family"):
        catalog.build_harbor_parser()


_FORMAT_PARSER_SAMPLE_FILES = {
    "csv": "a.csv",
    "docx": "a.docx",
    "epub": "a.epub",
    "excel": "a.xlsx",
    "html": "a.html",
    "image": "a.png",
    "json": "a.json",
    "markdown": "a.md",
    "pptx": "a.pptx",
    "text": "a.txt",
}


def _single_engine_family(
    registry: HarborParserRegistry,
    filename: str,
) -> HarborSingleEngineFamilyParser:
    family = registry.resolve(filename, None)
    assert isinstance(family, HarborSingleEngineFamilyParser)
    return family


def _engine_names(family: HarborSingleEngineFamilyParser) -> list[str]:
    return sorted(engine.name for engine in family.engines)


def test_format_parser_samples_cover_every_parser_type_but_pdf() -> None:
    assert sorted(_FORMAT_PARSER_SAMPLE_FILES) == [
        name for name in supported_parser_names() if name != "pdf"
    ]


@pytest.mark.parametrize(
    ("parser", "sample_file"),
    sorted(_FORMAT_PARSER_SAMPLE_FILES.items()),
)
def test_build_registry_one_format_definition_keeps_every_route_of_its_family(
    tmp_path: Path,
    parser: str,
    sample_file: str,
) -> None:
    config_path = _write_config(
        tmp_path,
        f"""
        version: 1
        parsers:
          custom:
            parser: {parser}
        """,
    )
    default_family = _single_engine_family(HarborParserFactory().create_registry(), sample_file)

    family = _single_engine_family(load_parser_catalog(config_path).build_registry(), sample_file)

    assert family.extensions == default_family.extensions
    assert family.mime_types == default_family.mime_types
    assert _engine_names(family) == _engine_names(default_family)


def test_build_registry_other_ocr_engine_replaces_the_default_image_engine(
    tmp_path: Path,
) -> None:
    config_path = _write_config(
        tmp_path,
        """
        version: 1
        parsers:
          custom-image:
            parser: image
            settings:
              ocr_engine: pytesseract
        """,
    )

    registry = load_parser_catalog(config_path).build_registry()

    assert _engine_names(_single_engine_family(registry, "scan.png")) == ["pytesseract"]
