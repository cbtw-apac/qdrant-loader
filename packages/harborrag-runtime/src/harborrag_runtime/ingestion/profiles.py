"""Processing identity of an ingestion run, shared by clients and workers.

The identity is built from configuration alone, so the same settings and files
give the same identity in every process.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from harborrag_core.ingestion import ProcessingProfile
from harborrag_engine.ingestion.chunking import ChunkingConfig, ChunkStrategy
from harborrag_engine.ingestion.chunking.config import cap_chunking_config
from harborrag_runtime.config.chunking import chunking_settings_from
from harborrag_runtime.config.errors import ParserConfigurationError
from harborrag_runtime.config.parsers import load_parser_catalog
from harborrag_runtime.config.settings import RuntimeSettings
from harborrag_runtime.ingestion_contracts import RunSettings

from .chunking_profile import chunk_strategy_fingerprint
from .document.normalization import CANONICAL_NORMALIZER_VERSION

# Source assertions and metadata observations have independent document supports.
# Legacy scope-owned assertions are rejected on reads until rebuilt and retired.
GRAPH_PROJECTION_VERSION = "graph-v5-unique-visible-edges"
VECTOR_PROJECTION_SCHEMA = "vector-v2"


def build_processing_profile(
    settings: RuntimeSettings,
    *,
    chunking_config: ChunkingConfig | None = None,
    chunking_strategies: tuple[ChunkStrategy, ...] = (),
    run_settings: RunSettings | None = None,
) -> ProcessingProfile:
    """Build the deterministic processing identity shared by clients and workers.

    Args:
        settings: Runtime settings naming the parser and chunking files.
        chunking_config: Profiles that replace those of ``chunking.yaml``. The
            refiner choice always comes from the file or its defaults.
        chunking_strategies: Extra chunking strategies of this deployment.
        run_settings: Per-run overrides. They change the identity only when
            they change the effective parser or limits.

    Returns:
        The identity every stage of the run compares against stored work.

    Raises:
        ParserConfigurationError: The parser catalog file is missing or
            unreadable, or is invalid when a run overrides the PDF parser.
    """
    chunking = chunking_settings_from(settings)
    chunk_config = chunking_config or chunking.config
    parser_profile = _parser_catalog_digest(settings.parser_config_path)
    if run_settings is not None:
        if run_settings.chunk_max_tokens is not None:
            chunk_config = cap_chunking_config(chunk_config, run_settings.chunk_max_tokens)
        pdf_parser = run_settings.pdf_parser
        if (
            pdf_parser is not None
            and pdf_parser != load_parser_catalog(settings.parser_config_path).enabled_pdf_backend()
        ):
            parser_profile = f"{parser_profile}+pdf-{pdf_parser}"
    return ProcessingProfile(
        parser_profile=parser_profile,
        normalizer_version=CANONICAL_NORMALIZER_VERSION,
        chunk_strategy=chunk_strategy_fingerprint(
            chunk_config,
            chunking_strategies,
            refiner=chunking.refiner,
        ),
        dense_encoder_profile=settings.dense_encoder_profile,
        sparse_encoder_profile=settings.sparse_encoder_profile,
        graph_projection_version=GRAPH_PROJECTION_VERSION,
        vector_projection_schema=VECTOR_PROJECTION_SCHEMA,
    )


def configuration_file_digest(prefix: str, path: Path) -> str:
    """Label the content digest of a configuration file with ``prefix``.

    Passes on the ``OSError`` of a file that is missing or cannot be read.

    Args:
        prefix: What the file configures, such as ``parser``.
        path: The configuration file.

    Returns:
        The prefix and the first 16 hexadecimal digits of the SHA-256 digest.
    """
    digest = sha256(path.read_bytes()).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _parser_catalog_digest(path: Path) -> str:
    """Digest the parser catalog, reporting a missing file as a configuration error."""
    try:
        return configuration_file_digest("parser", path)
    except OSError as error:
        reason = error.strerror or type(error).__name__
        raise ParserConfigurationError(
            f"Parser configuration file cannot be read: {path} ({reason})"
        ) from error
