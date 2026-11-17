from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text

from harborrag_adapters.repositories.database.control_plane.migrations import (
    _build_config,
    run_migrations,
)
from harborrag_adapters.repositories.database.ingestion_control.topology.schema import (
    TOPOLOGY_POLICIES,
)

pytestmark = pytest.mark.unit


def test_permission_migration_preserves_legacy_jobs_but_does_not_grant_access(
    tmp_path: Path,
) -> None:
    """Migration 0022 keeps legacy topology jobs and grants no permission by itself."""
    path = tmp_path / "legacy-topology.db"
    config = _build_config(f"sqlite+aiosqlite:///{path}")
    command.upgrade(config, "0021")
    engine = create_engine(f"sqlite:///{path}")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO topology_jobs (job_id,tenant_id,source_scope_id,document_id,document_version_id,"
                    "policy_revision,fingerprint,policy,state,fence,attempts,created_at) "
                    "VALUES ('legacy','tenant','scope','doc','version',1,'fingerprint','{}','accepted',1,1,'2026-09-08')"
                )
            )
        command.upgrade(config, "0022")
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT config_epoch,permission_dependencies FROM topology_jobs WHERE job_id='legacy'"
                )
            ).one()
            assert row == (0, "[]")
            assert (
                connection.execute(
                    text("SELECT count(*) FROM topology_indexing_configs")
                ).scalar_one()
                == 0
            )
            assert (
                connection.execute(
                    text("SELECT count(*) FROM topology_build_permissions")
                ).scalar_one()
                == 0
            )
        command.downgrade(config, "0021")
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT job_id FROM topology_jobs")).scalar_one()
                == "legacy"
            )
    finally:
        engine.dispose()


def test_published_graph_conflicts_schema_upgrades_to_the_current_head(
    tmp_path: Path,
) -> None:
    """A database stamped with dev's published 0020 must run every new migration."""
    path = tmp_path / "published-0020.db"
    dsn = f"sqlite+aiosqlite:///{path}"
    config = _build_config(dsn)
    command.upgrade(config, "0020")
    engine = create_engine(f"sqlite:///{path}")
    try:
        with engine.begin() as connection:
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "0020"
            )
            connection.execute(
                text(
                    "INSERT INTO graph_conflicts "
                    "(id,tenant_id,conflict_type,subject_node_key,description,status,detected_at) "
                    "VALUES ('existing','tenant','duplicate','node-a','published conflict','open',"
                    "'2026-09-15')"
                )
            )

        run_migrations(dsn)

        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "0048"
            )
            assert (
                connection.execute(
                    text("SELECT description FROM graph_conflicts WHERE id = 'existing'")
                ).scalar_one()
                == "published conflict"
            )
        tables = set(inspect(engine).get_table_names())
        assert {"topology_jobs", "topology_permission_snapshots", "summary_scopes"} <= tables
    finally:
        engine.dispose()


def test_migration_adds_topology_tables_and_round_trips_without_document_loss(
    tmp_path: Path,
) -> None:
    """The topology tables appear on upgrade and a round trip loses no document."""
    path = tmp_path / "migration.db"
    dsn = f"sqlite+aiosqlite:///{path}"
    config = _build_config(dsn)
    command.upgrade(config, "0019")
    engine = create_engine(f"sqlite:///{path}")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO documents (document_id, tenant_id, source_scope_id, connector_type, "
                    "connection_id, source_item_id, active_document_version_id, created_at, updated_at) "
                    "VALUES ('document', 'tenant', 'captured-scope', 'confluence', 'connection', "
                    "'source-item', 'version', '2026-09-08', '2026-09-08')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO document_versions (document_version_id, document_id, canonical_content_hash, "
                    "retrieval_metadata_hash, processing_fingerprint, admission_change_key, status, created_at, updated_at) "
                    "VALUES ('version', 'document', 'hash', 'metadata', 'processing', 'admission', "
                    "'ACTIVE', '2026-09-08', '2026-09-08')"
                )
            )
        run_migrations(dsn)
        run_migrations(dsn)
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT source_scope_id FROM document_versions WHERE document_version_id = 'version'"
                    )
                ).scalar_one()
                == "captured-scope"
            )
        tables = set(inspect(engine).get_table_names())
        expected = {
            name
            for name in TOPOLOGY_POLICIES.metadata.tables
            if name.startswith(("topology_", "summary_"))
        }
        assert {
            "summary_scopes",
            "summary_bindings",
            "summary_cache",
            "summary_tenants",
        } <= expected
        assert expected <= tables
        command.downgrade(config, "0019")
        tables = set(inspect(engine).get_table_names())
        assert not expected & tables
        assert "documents" in tables and "document_versions" in tables
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT document_version_id FROM document_versions")
                ).scalar_one()
                == "version"
            )
        command.upgrade(config, "head")
        assert expected <= set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
