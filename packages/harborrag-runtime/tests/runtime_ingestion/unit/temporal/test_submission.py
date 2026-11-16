"""Secret-free, deterministic source submission behavior."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from harborrag_runtime.config.errors import ConnectorConfigurationError
from harborrag_runtime.config.settings import RuntimeSettings
from harborrag_runtime.execution.source_submission import (
    SourceSubmissionDefaults,
    prepare_source_submission,
)
from harborrag_runtime.ingestion.connections import ResolvedConnection
from harborrag_runtime.temporal.schemas import SourceQuery
from harborrag_runtime.temporal.submission import (
    SourceSubmission,
    build_source_input,
)
from runtime_ingestion.connection_support import resolved_connection

pytestmark = pytest.mark.unit

_JIRA_CREDENTIALS = {
    "base_url": "https://jira.example.test",
    "email": "bot@example.test",
    "api_token": {"secret_ref": "secret://db/first"},
}


def _settings(tmp_path: Path) -> RuntimeSettings:
    parsers = tmp_path / "parsers.yaml"
    parsers.write_text("version: 1\n", encoding="utf-8")
    return RuntimeSettings(parser_config_path=parsers)


def _jira(**changes: Any) -> ResolvedConnection:
    credentials = {**_JIRA_CREDENTIALS, **changes.pop("credentials", {})}
    config = {"project_keys": ["DOCS"], **changes.pop("config", {})}
    return resolved_connection("jira", credentials=credentials, config=config, **changes)


def _submission(**changes: object) -> SourceSubmission:
    values: dict[str, object] = {
        "task_id": "task-1",
        "tenant_id": "tenant-1",
        "connector_name": "docs",
    }
    values.update(changes)
    return SourceSubmission(**values)  # type: ignore[arg-type]  # test overrides any field


def test_submission_builds_deterministic_secret_free_source_identity(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)

    first = build_source_input(settings, _submission(), connection=_jira())
    second = build_source_input(settings, _submission(), connection=_jira())

    assert first == second
    assert first.connector_type == "jira"
    assert first.connection_id == "docs"
    assert first.source_scope_id.startswith("scope-")
    assert first.configuration_fingerprint.startswith("connection-")
    assert first.processing.vector_projection_schema == "vector-v2"
    assert first.processing.graph_projection_version == "graph-v5-unique-visible-edges"
    assert first.discovery_page_size == 50
    assert first.discovery_concurrency == 4


def test_a_rotated_secret_reference_changes_the_fingerprint_but_not_the_scope(
    tmp_path: Path,
) -> None:
    rotated_reference = _jira(credentials={"api_token": {"secret_ref": "secret://db/second"}})

    first = build_source_input(_settings(tmp_path), _submission(), connection=_jira())
    second = build_source_input(_settings(tmp_path), _submission(), connection=rotated_reference)

    assert first.source_scope_id == second.source_scope_id
    assert first.configuration_fingerprint != second.configuration_fingerprint


def test_query_changes_scope_without_changing_connector_configuration(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)

    first = build_source_input(
        settings, _submission(query=SourceQuery(pattern="*.md")), connection=_jira()
    )
    second = build_source_input(
        settings, _submission(query=SourceQuery(pattern="*.txt")), connection=_jira()
    )

    assert first.source_scope_id != second.source_scope_id
    assert first.configuration_fingerprint == second.configuration_fingerprint


def test_execution_toggles_do_not_split_scope_and_connection_can_disable_attachments(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)

    enabled_request = build_source_input(
        settings,
        _submission(
            query=SourceQuery(
                include_attachments=True,
                filters_json='{"include_comments":true,"build_graph":true}',
            )
        ),
        connection=_jira(),
    )
    disabled_request = build_source_input(
        settings,
        _submission(
            query=SourceQuery(
                include_attachments=False,
                filters_json='{"include_comments":false,"build_graph":false}',
            )
        ),
        connection=_jira(),
    )

    assert enabled_request.query.include_attachments is False
    assert disabled_request.query.include_attachments is False
    assert enabled_request.source_scope_id == disabled_request.source_scope_id


def test_config_jql_reaches_the_query_but_editing_it_keeps_the_scope(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    first = build_source_input(
        settings, _submission(), connection=_jira(config={"jql": "project = CPM"})
    )
    second = build_source_input(
        settings, _submission(), connection=_jira(config={"jql": "project = HR"})
    )

    assert '"jql":"project = CPM"' in first.query.filters_json
    assert first.source_scope_id == second.source_scope_id
    assert first.configuration_fingerprint != second.configuration_fingerprint


def test_run_jql_narrows_the_connection_jql_instead_of_replacing_it(tmp_path: Path) -> None:
    source = build_source_input(
        _settings(tmp_path),
        _submission(query=SourceQuery(filters_json='{"jql":"project = HR"}')),
        connection=_jira(config={"jql": "project = CPM"}),
    )

    assert json.loads(source.query.filters_json)["jql"] == "(project = CPM) and (project = HR)"


def test_an_empty_run_jql_keeps_the_connection_jql(tmp_path: Path) -> None:
    source = build_source_input(
        _settings(tmp_path),
        _submission(query=SourceQuery(filters_json='{"jql":""}')),
        connection=_jira(config={"jql": "project = CPM"}),
    )

    assert json.loads(source.query.filters_json)["jql"] == "project = CPM"


@pytest.mark.parametrize(
    "config",
    [
        pytest.param({"jql": "project = CPM"}, id="connection-jql"),
        pytest.param({}, id="no-connection-jql"),
    ],
)
def test_an_empty_run_jql_gets_the_scope_of_a_run_without_jql(
    tmp_path: Path, config: dict[str, Any]
) -> None:
    settings = _settings(tmp_path)
    empty_jql = _submission(query=SourceQuery(filters_json='{"jql":""}'))
    own_jql = _submission(query=SourceQuery(filters_json='{"jql":"status = Done"}'))

    omitted = build_source_input(settings, _submission(), connection=_jira(config=config))
    empty = build_source_input(settings, empty_jql, connection=_jira(config=config))
    narrowed = build_source_input(settings, own_jql, connection=_jira(config=config))

    assert empty.source_scope_id == omitted.source_scope_id
    assert narrowed.source_scope_id != omitted.source_scope_id


def test_run_filter_without_a_source_type_narrower_is_rejected(tmp_path: Path) -> None:
    connection = _jira(config={"jql": "project = CPM"})
    without_narrower = replace(connection, spec=replace(connection.spec, query_narrowers={}))

    with pytest.raises(ConnectorConfigurationError, match="can only narrow"):
        prepare_source_submission(
            _settings(tmp_path),
            _submission(query=SourceQuery(filters_json='{"jql":"project = HR"}')),
            connection=without_narrower,
        )


@pytest.mark.parametrize(
    "filters_json",
    [
        pytest.param('{"jql":"x = 1) or (project = HR"}', id="jql-closes-its-group"),
        pytest.param('{"jql":["project = HR"]}', id="jql-not-a-string"),
    ],
)
def test_run_jql_that_cannot_narrow_the_connection_jql_is_rejected(
    tmp_path: Path, filters_json: str
) -> None:
    with pytest.raises(ConnectorConfigurationError, match="jql"):
        prepare_source_submission(
            _settings(tmp_path),
            _submission(query=SourceQuery(filters_json=filters_json)),
            connection=_jira(config={"jql": "project = CPM"}),
        )


def test_editing_the_connection_jql_keeps_the_scope_of_a_run_with_its_own_jql(
    tmp_path: Path,
) -> None:
    run = _submission(query=SourceQuery(filters_json='{"jql":"status = Done"}'))

    first = build_source_input(
        _settings(tmp_path), run, connection=_jira(config={"jql": "project = CPM"})
    )
    second = build_source_input(
        _settings(tmp_path), run, connection=_jira(config={"jql": "project = HR"})
    )

    assert first.source_scope_id == second.source_scope_id


def test_non_secret_connection_change_updates_configuration_fingerprint(
    tmp_path: Path,
) -> None:
    first = build_source_input(_settings(tmp_path), _submission(), connection=_jira())
    second = build_source_input(
        _settings(tmp_path),
        _submission(),
        connection=_jira(credentials={"base_url": "https://jira-b.example.test"}),
    )

    assert first.configuration_fingerprint != second.configuration_fingerprint


def test_the_source_key_names_the_connection_and_an_explicit_scope_is_preserved(
    tmp_path: Path,
) -> None:
    source = build_source_input(
        _settings(tmp_path),
        _submission(connection_id="shared-files", source_scope_id="engineering-docs"),
        connection=_jira(source_key="shared-files"),
    )

    assert source.connection_id == "shared-files"
    assert source.connector_name == "shared-files"
    assert source.source_scope_id == "engineering-docs"


@pytest.mark.parametrize(
    "filters_json",
    [
        '{"access_token":"secret"}',
        '{"nested":{"provider_api_key":"secret"}}',
    ],
)
def test_source_query_rejects_credentials(filters_json: str) -> None:
    with pytest.raises(ValueError, match="cannot contain credentials"):
        SourceQuery(filters_json=filters_json)


@pytest.mark.parametrize("updated_after", ["not-a-date", "2026-07-31T10:00:00"])
def test_source_query_requires_an_aware_iso_timestamp(updated_after: str) -> None:
    with pytest.raises(ValueError, match="updated_after"):
        SourceQuery(updated_after=updated_after)


def _settings_with_ingestion_defaults(
    tmp_path: Path,
    *,
    batch_size: int,
    document_concurrency: int,
) -> RuntimeSettings:
    settings = _settings(tmp_path)
    temporal_config = tmp_path / "temporal.yaml"
    temporal_config.write_text(
        f"version: 1\ningestion:\n  batch_size: {batch_size}\n"
        f"  document_concurrency: {document_concurrency}\n",
        encoding="utf-8",
    )
    return settings.model_copy(update={"temporal_config_path": temporal_config})


def test_unset_batching_falls_back_to_the_configured_ingestion_defaults(
    tmp_path: Path,
) -> None:
    settings = _settings_with_ingestion_defaults(tmp_path, batch_size=5, document_concurrency=5)

    source = build_source_input(settings, _submission(), connection=_jira())

    assert source.batch_size == 5
    assert source.document_concurrency == 5


def test_explicit_batching_overrides_the_configured_ingestion_defaults(
    tmp_path: Path,
) -> None:
    settings = _settings_with_ingestion_defaults(tmp_path, batch_size=5, document_concurrency=5)

    source = build_source_input(
        settings,
        _submission(batch_size=200, document_concurrency=8),
        connection=_jira(),
    )

    assert source.batch_size == 200
    assert source.document_concurrency == 8


def test_neutral_preparation_uses_injected_defaults_without_reading_temporal_config(
    tmp_path: Path,
) -> None:
    invalid_temporal = tmp_path / "temporal.yaml"
    invalid_temporal.write_text("not: a temporal configuration", encoding="utf-8")
    settings = _settings(tmp_path).model_copy(update={"temporal_config_path": invalid_temporal})

    source = prepare_source_submission(
        settings,
        _submission(),
        connection=_jira(),
        defaults=SourceSubmissionDefaults(batch_size=12, document_concurrency=3),
    )

    assert source.batch_size == 12
    assert source.document_concurrency == 3
    assert not hasattr(source, "workflow_options")


def _local(tmp_path: Path) -> ResolvedConnection:
    source = tmp_path / "docs"
    source.mkdir(exist_ok=True)
    return resolved_connection(
        "local_file", source_key="files", config={"source_path": str(source)}
    )


def test_unknown_local_filter_keys_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConnectorConfigurationError) as raised:
        prepare_source_submission(
            _settings(tmp_path),
            _submission(connector_name="files", query=SourceQuery(filters_json='{"bogus": 1}')),
            connection=_local(tmp_path),
        )

    message = str(raised.value)
    assert "bogus" in message
    assert "allowed_extensions" in message
    assert "include_globs" in message


def test_known_local_filter_keys_are_accepted(tmp_path: Path) -> None:
    prepared = prepare_source_submission(
        _settings(tmp_path),
        _submission(
            connector_name="files",
            query=SourceQuery(
                filters_json='{"extensions": [".md"], "include_comments": false, "files": []}'
            ),
        ),
        connection=_local(tmp_path),
    )

    assert prepared.connector_type == "local"
