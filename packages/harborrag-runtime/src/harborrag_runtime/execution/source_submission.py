"""Preparation of one source ingestion run from a connection and a submission.

Provider-neutral: turns what a caller asked for and the connection snapshot into
the deterministic input every activity of the run receives. Connection config
filters are a ceiling a run can only narrow, with the function the source type
registers for that filter, and the source scope id comes from the run's own
query, so editing connection config keeps the scope.

Start from: prepare_source_submission.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from hashlib import sha256

from harborrag_runtime.config.errors import ConnectorConfigurationError
from harborrag_runtime.config.settings import RuntimeSettings
from harborrag_runtime.ingestion.connections import ResolvedConnection
from harborrag_runtime.ingestion.profiles import build_processing_profile
from harborrag_runtime.ingestion_contracts import PreparedSourceSubmission, SourceSubmission
from harborrag_runtime.serialization import to_json_value
from harborrag_runtime.source_query import ProcessingProfileInput, SourceQuery

_EXECUTION_FILTERS = ("include_comments", "build_graph")


@dataclass(frozen=True, slots=True)
class SourceSubmissionDefaults:
    """Execution policy supplied by the selected provider's composition.

    Args:
        batch_size: Documents per batch when the run sets none.
        document_concurrency: Documents processed at once when neither the run nor
            the connection's run settings set it.
    """

    batch_size: int = 200
    document_concurrency: int = 8


def prepare_source_submission(
    settings: RuntimeSettings,
    submission: SourceSubmission,
    *,
    connection: ResolvedConnection,
    defaults: SourceSubmissionDefaults = SourceSubmissionDefaults(),
) -> PreparedSourceSubmission:
    """Turn a resolved connection and a submission into a provider-neutral run input.

    A ``ConnectorConfigurationError`` passes through when a local query names a
    filter the connector ignores, or when the run sets a filter the connection
    configures and the run's value cannot narrow it.

    Args:
        settings: Runtime settings that pick the processing profile.
        submission: What the caller asked to ingest.
        connection: The connection snapshot the run will use.
        defaults: Batch and concurrency policy of the execution provider.

    Returns:
        The deterministic input every activity of the run receives.
    """
    if connection.provider == "local":
        _require_known_local_filters(submission.query)
    source_key = connection.snapshot.source_key
    query = _effective_query(connection, submission.query)
    source_scope_id = submission.source_scope_id or _source_scope_id(
        tenant_id=submission.tenant_id,
        connector_name=source_key,
        connector_type=connection.provider,
        connection_id=source_key,
        query=_without_empty_query_fields(submission.query, connection.spec.query_fields),
    )
    run_settings = connection.run_settings
    processing = build_processing_profile(settings, run_settings=run_settings)
    batch_size = submission.batch_size if submission.batch_size is not None else defaults.batch_size
    document_concurrency = (
        submission.document_concurrency
        if submission.document_concurrency is not None
        else run_settings.document_concurrency
        if run_settings is not None and run_settings.document_concurrency is not None
        else defaults.document_concurrency
    )
    return PreparedSourceSubmission(
        task_id=submission.task_id,
        tenant_id=submission.tenant_id,
        connector_name=source_key,
        connector_type=connection.provider,
        connection_id=source_key,
        source_scope_id=source_scope_id,
        configuration_fingerprint=connection.fingerprint,
        processing=ProcessingProfileInput(
            parser_profile=processing.parser_profile,
            normalizer_version=processing.normalizer_version,
            chunk_strategy=processing.chunk_strategy,
            dense_encoder_profile=processing.dense_encoder_profile,
            sparse_encoder_profile=processing.sparse_encoder_profile,
            graph_projection_version=processing.graph_projection_version,
            vector_projection_schema=processing.vector_projection_schema,
        ),
        query=query,
        force_reprocess=submission.force_reprocess,
        discovery_page_size=submission.discovery_page_size,
        discovery_concurrency=submission.discovery_concurrency,
        document_concurrency=document_concurrency,
        missing_threshold=submission.missing_threshold,
        batch_size=batch_size,
        continue_after_batches=submission.continue_after_batches,
        run_settings=run_settings,
    )


def _require_known_local_filters(query: SourceQuery) -> None:
    """Reject filter keys the local connector would silently ignore."""
    from harborrag_adapters.connectors.local.filters import LOCAL_QUERY_FILTER_KEYS

    filters = json.loads(query.filters_json)
    if not isinstance(filters, dict):
        return
    unknown = sorted(str(key) for key in filters if key not in LOCAL_QUERY_FILTER_KEYS)
    if unknown:
        raise ConnectorConfigurationError(
            f"Unknown filter keys for a local connector: {', '.join(unknown)}. "
            f"Allowed keys: {', '.join(sorted(LOCAL_QUERY_FILTER_KEYS))}"
        )


def _source_scope_id(
    *,
    tenant_id: str,
    connector_name: str,
    connector_type: str,
    connection_id: str,
    query: SourceQuery,
) -> str:
    """Return the stable scope id of one connection and the query the run submitted."""
    payload = {
        "tenant_id": tenant_id,
        "connector_name": connector_name,
        "connector_type": connector_type,
        "connection_id": connection_id,
        "query": _scope_query(query),
    }
    return f"scope-{_digest(payload)[:32]}"


def _effective_query(connection: ResolvedConnection, query: SourceQuery) -> SourceQuery:
    """Apply the connection's feature ceilings and config filters to the run query.

    A filter the connection configures is a ceiling the run can only narrow: a run
    that leaves the key unset or empty gets the configured value, and a run value is
    combined with it by ``_narrowed_filter``, whose ``ConnectorConfigurationError``
    passes through when the two cannot be combined. ``_without_empty_query_fields``
    keeps that unset-or-empty equivalence in the source scope id.

    Args:
        connection: The connection snapshot the run will use.
        query: The query the run submitted.

    Returns:
        The query every activity of the run receives.
    """
    include_attachments = query.include_attachments and connection.include_attachments()
    config_filters = connection.query_filters()
    if not config_filters:
        return replace(query, include_attachments=include_attachments)
    filters = json.loads(query.filters_json)
    for key, connection_value in config_filters.items():
        run_value = filters.get(key)
        filters[key] = (
            _narrowed_filter(connection, key, connection_value, run_value)
            if run_value
            else connection_value
        )
    return replace(
        query,
        include_attachments=include_attachments,
        filters_json=json.dumps(filters, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
    )


def _narrowed_filter(
    connection: ResolvedConnection, key: str, connection_value: object, run_value: object
) -> str:
    """Combine a run's value for a configured filter with the connection's, narrowing it.

    The source type's ``query_narrowers`` own how a filter narrows; Jira, for one,
    ANDs a run ``jql`` onto the connection's so the run can only select fewer issues.

    Args:
        connection: The connection snapshot, whose source type names the narrowers.
        key: Filter name both the connection and the run set.
        connection_value: The connection's configured value.
        run_value: The run's value.

    Returns:
        The combined filter value.

    Raises:
        ConnectorConfigurationError: The source type has no narrower for the filter,
            either value is not text, or the narrower refuses to combine them.
    """
    narrow = connection.spec.query_narrowers.get(key)
    if narrow is None or not isinstance(connection_value, str):
        raise ConnectorConfigurationError(
            f"A run cannot replace the connection's {key} filter; it can only narrow it"
        )
    if not isinstance(run_value, str):
        raise ConnectorConfigurationError(f"A run {key} filter must be text")
    try:
        return narrow(connection_value, run_value)
    except ValueError as error:
        raise ConnectorConfigurationError(
            f"Run {key} cannot narrow the connection {key}: {error}"
        ) from error


def _without_empty_query_fields(query: SourceQuery, query_fields: frozenset[str]) -> SourceQuery:
    """Drop the source type's query fields a run left empty from its filters.

    An empty query field selects what leaving it out selects, so both runs must
    get one source scope id.

    Args:
        query: The query the run submitted.
        query_fields: The source type's query fields, such as Jira ``jql``.

    Returns:
        ``query`` itself when nothing was dropped, else a copy without the empty fields.
    """
    filters = json.loads(query.filters_json)
    if not isinstance(filters, dict):
        return query
    kept = {key: value for key, value in filters.items() if value or key not in query_fields}
    if len(kept) == len(filters):
        return query
    return replace(
        query,
        filters_json=json.dumps(kept, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
    )


def _scope_query(query: SourceQuery) -> dict[str, object]:
    """Keep execution controls out of the stable source membership scope."""
    values = asdict(query)
    values.pop("include_attachments", None)
    filters = json.loads(query.filters_json)
    if isinstance(filters, dict):
        for key in _EXECUTION_FILTERS:
            filters.pop(key, None)
        values["filters_json"] = json.dumps(
            filters,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    return values


def _digest(payload: Mapping[str, object]) -> str:
    """Return the SHA-256 hex digest of a payload's canonical JSON."""
    encoded = json.dumps(
        to_json_value(payload),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()
