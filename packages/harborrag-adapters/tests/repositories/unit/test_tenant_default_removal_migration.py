from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from harborrag_adapters.repositories.database.control_plane.migrations import _build_config
from harborrag_adapters.repositories.database.control_plane.schemas import Base

pytestmark = pytest.mark.unit

_TABLES = (
    "projects",
    "sources",
    "secrets",
    "jobs",
    "activity",
    "providers",
    "workspace_settings",
    "members",
    "graph_conflicts",
)
_BEFORE = "0047"
_AFTER = "0048"
_MEMBER_WITHOUT_TENANT = (
    "INSERT INTO members (id,subject,role,created_at) "
    "VALUES ('m-none','nobody@example.com','reader','2026-10-01 00:00:00')"
)
_MEMBER_OF_ACME = (
    "INSERT INTO members (id,tenant_id,subject,role,created_at) "
    "VALUES ('m-acme','acme','alex@example.com','admin','2026-10-01 00:00:00')"
)


@pytest.fixture
def config(tmp_path: Path) -> Config:
    """Alembic config for an empty SQLite control database."""
    return _build_config(f"sqlite+aiosqlite:///{tmp_path / 'control.db'}")


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    """Synchronous engine on the database ``config`` migrates."""
    engine = create_engine(f"sqlite:///{tmp_path / 'control.db'}")
    yield engine
    engine.dispose()


def _tenant_defaults(engine: Engine) -> dict[str, str | None]:
    inspector = inspect(engine)
    return {
        table: column["default"]
        for table in _TABLES
        for column in inspector.get_columns(table)
        if column["name"] == "tenant_id"
    }


def test_upgrade_removes_the_tenant_default_from_every_table(
    config: Config, engine: Engine
) -> None:
    """Issue #106: no control-plane table keeps a database default for the tenant."""
    command.upgrade(config, _AFTER)

    assert _tenant_defaults(engine) == dict.fromkeys(_TABLES)


def test_insert_without_a_tenant_is_rejected_after_the_upgrade(
    config: Config, engine: Engine
) -> None:
    """Issue #106: a row written without a tenant fails instead of joining DEFAULT."""
    command.upgrade(config, _AFTER)

    with pytest.raises(IntegrityError, match="members.tenant_id"), engine.begin() as connection:
        connection.execute(text(_MEMBER_WITHOUT_TENANT))


def test_upgrade_keeps_existing_rows_and_their_tenant(config: Config, engine: Engine) -> None:
    """Dropping the default leaves stored rows and their tenant untouched."""
    command.upgrade(config, _BEFORE)
    with engine.begin() as connection:
        connection.execute(text(_MEMBER_OF_ACME))

    command.upgrade(config, _AFTER)

    with engine.connect() as connection:
        members = connection.execute(text("SELECT id, tenant_id, role FROM members")).all()
    assert members == [("m-acme", "acme", "admin")]


def test_downgrade_restores_the_tenant_default(config: Config, engine: Engine) -> None:
    """The downgrade puts the default back so the previous release keeps working."""
    command.upgrade(config, _AFTER)

    command.downgrade(config, _BEFORE)

    assert _tenant_defaults(engine) == dict.fromkeys(_TABLES, "'DEFAULT'")


def test_models_declare_no_tenant_default() -> None:
    """A schema built from the models rejects a missing tenant like a migrated one."""
    defaults = {table: Base.metadata.tables[table].c.tenant_id.server_default for table in _TABLES}

    assert defaults == dict.fromkeys(_TABLES)
