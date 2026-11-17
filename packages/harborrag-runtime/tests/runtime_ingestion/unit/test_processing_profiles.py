"""Processing identity follows effective chunking inputs rather than a manual label."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from harborrag_core.ingestion import ChangeFingerprintBuilder
from harborrag_engine.ingestion.chunking import ChunkingConfig
from harborrag_engine.ingestion.chunking.sources import CanonicalDocumentChunkingStrategy
from harborrag_engine.ingestion.chunking.table.rendering import TableRenderer
from harborrag_runtime.config import ParserConfigurationError
from harborrag_runtime.config.settings import RuntimeSettings
from harborrag_runtime.ingestion.chunking_profile import (
    chunk_strategy_fingerprint,
    default_chunking_config,
)
from harborrag_runtime.ingestion.profiles import build_processing_profile
from harborrag_runtime.tokenization import ApproximateTokenCounter

pytestmark = pytest.mark.unit


def test_profile_mapping_order_does_not_change_processing_identity() -> None:
    config = default_chunking_config()
    reordered = replace(
        config,
        profiles=dict(reversed(tuple(config.profiles.items()))),
        source_profiles=dict(reversed(tuple(config.source_profiles.items()))),
    )
    assert chunk_strategy_fingerprint(config) == chunk_strategy_fingerprint(reordered)


@pytest.mark.parametrize("change", ["tokens", "headers", "routes", "configuration", "routing"])
def test_segmentation_affecting_configuration_changes_identity(change: str) -> None:
    config = default_chunking_config()
    if change == "tokens":
        profile = config.profiles["canonical"]
        changed_profile = replace(profile, limits=replace(profile.limits, target_tokens=650))
        changed = replace(config, profiles={**config.profiles, "canonical": changed_profile})
    elif change == "headers":
        changed_profile = replace(config.profiles["canonical"], repeat_table_headers=False)
        changed = replace(config, profiles={**config.profiles, "canonical": changed_profile})
    elif change == "routes":
        changed = replace(config, create_route_chunks=False)
    elif change == "routing":
        changed = replace(config, source_profiles={**config.source_profiles, "jira": "canonical"})
    else:
        changed = replace(config, configuration_version="changed")
    assert chunk_strategy_fingerprint(config) != chunk_strategy_fingerprint(changed)


@pytest.mark.parametrize(
    "component", [CanonicalDocumentChunkingStrategy, ApproximateTokenCounter, TableRenderer]
)
def test_implementation_versions_automatically_change_processing_identity(
    component: type, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = default_chunking_config()
    original = chunk_strategy_fingerprint(config)
    monkeypatch.setattr(component, "version", "new-version")
    assert chunk_strategy_fingerprint(config) != original


def test_tokenizer_identity_automatically_changes_processing_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = default_chunking_config()
    original = chunk_strategy_fingerprint(config)
    monkeypatch.setattr(ApproximateTokenCounter, "name", "other-counter")
    assert chunk_strategy_fingerprint(config) != original


def test_additional_strategy_versions_are_part_of_effective_profile() -> None:
    class CustomStrategy(CanonicalDocumentChunkingStrategy):
        name = "custom"
        version = "1"

    strategy = CustomStrategy(ApproximateTokenCounter())
    config = default_chunking_config()
    original = chunk_strategy_fingerprint(config, (strategy,))
    strategy.version = "2"
    assert chunk_strategy_fingerprint(config, (strategy,)) != original
    assert chunk_strategy_fingerprint(config) != original


def test_processing_profile_uses_custom_config_and_changes_admission_fingerprint(
    tmp_path: Path,
) -> None:
    parser = tmp_path / "parsers.yaml"
    parser.write_text("version: 1\n", encoding="utf-8")
    settings = RuntimeSettings(parser_config_path=parser)
    default = build_processing_profile(settings)
    custom = build_processing_profile(
        settings, chunking_config=ChunkingConfig(create_route_chunks=False)
    )
    builder = ChangeFingerprintBuilder()

    assert default.graph_projection_version == "graph-v5-unique-visible-edges"
    assert default.chunk_strategy == chunk_strategy_fingerprint(default_chunking_config())
    assert builder.processing_fingerprint(profile=default) != builder.processing_fingerprint(
        profile=custom
    )


def test_build_processing_profile_missing_parser_catalog_is_a_configuration_error(
    tmp_path: Path,
) -> None:
    missing_catalog = tmp_path / "parsers.yaml"

    with pytest.raises(ParserConfigurationError) as error:
        build_processing_profile(RuntimeSettings(parser_config_path=missing_catalog))

    assert str(missing_catalog) in str(error.value)
