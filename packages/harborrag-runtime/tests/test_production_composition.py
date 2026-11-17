"""CompositionRoot.production boots against a real (SQLite) control DB (ST8)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

import pytest

from harborrag_core.contracts.errors import HarborConfigurationError
from harborrag_core.domain.project import Project
from harborrag_core.ports.usage import ModelUsageRecord
from harborrag_runtime.composition import CompositionRoot
from harborrag_runtime.composition.control_plane import secrets_encryption_key
from harborrag_runtime.config.settings import DEFAULT_CONTROL_DB_URL, RuntimeSettings


def _production(tmp_path: Path) -> CompositionRoot:
    """Composition against a tmp SQLite control DB."""
    dsn = f"sqlite+aiosqlite:///{tmp_path}/control.db"
    return CompositionRoot.production(RuntimeSettings(control_db_url=dsn))


@pytest.mark.whitebox
def test_production_composition_migrates_and_reports_ready(tmp_path: Path, caplog) -> None:
    """production() migrates, probes the DB and reports the stamped revision as ready."""
    with caplog.at_level(logging.INFO, logger="harborrag.runtime.composition"):
        composition = _production(tmp_path)
    assert composition.mode == "production"
    diagnostics = composition.diagnostics()
    assert diagnostics["mode"] == "production"
    runtime = diagnostics["runtime"]
    assert isinstance(runtime, dict)
    assert runtime["ready"] is True
    control_db = runtime["control_db"]
    assert control_db["ping"] == "ok"
    assert control_db["migrations"] == "0048"
    assert control_db["scheme"] == "sqlite+aiosqlite"
    assert "Control-plane composition completed" in caplog.text
    assert "database_scheme=sqlite+aiosqlite ready=True migration=0048" in caplog.text


@pytest.mark.asyncio
@pytest.mark.whitebox
async def test_production_repositories_hit_the_real_database(
    tmp_path: Path,
) -> None:
    """The composed port-typed repositories read/write the migrated DB."""
    composition = _production(tmp_path)
    try:
        assert composition.control_plane is not None
        projects = composition.control_plane.projects
        await projects.create(
            Project(id="p1", tenant_id="DEFAULT", name="Docs", collection="docs_main")
        )
        fetched = await projects.get("p1", tenant_ids=None)
        assert fetched is not None and fetched.name == "Docs"
        assert composition.control_plane.memories is not None
        usage = composition.control_plane.model_usage
        assert usage is not None
        await usage.record(
            ModelUsageRecord(
                tenant_id="DEFAULT",
                user_id="user-1",
                principal_id="principal-1",
                logical_model="chat-default",
                provider="openai",
                provider_model="gpt-4.1-mini",
                prompt_tokens=8,
                completion_tokens=2,
                total_tokens=10,
            )
        )
        totals = await usage.totals(tenant_id="DEFAULT", user_id="user-1")
        assert totals.requests == 1
        assert totals.total_tokens == 10
    finally:
        await composition.aclose()


@pytest.mark.whitebox
def test_production_migration_failure_aborts_startup(tmp_path: Path) -> None:
    """An unreachable control DB must not leave a degraded process serving traffic."""
    settings = RuntimeSettings(control_db_url=f"sqlite+aiosqlite:///{tmp_path}/nodir/x.db")
    with pytest.raises(HarborConfigurationError, match="migrations failed"):
        CompositionRoot.production(settings)


@pytest.mark.whitebox
def test_production_probe_failure_aborts_startup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A control DB that migrates but fails its probe must not start the process."""
    monkeypatch.setattr(
        "harborrag_runtime.composition.control_plane._probe_control_db",
        lambda _dsn: {"ping": "failed", "error": "probe failed", "scheme": "sqlite"},
    )

    with pytest.raises(HarborConfigurationError, match="database probe failed"):
        _production(tmp_path)


@pytest.mark.whitebox
@pytest.mark.parametrize("env", ["staging", "prod"])
def test_prod_env_refuses_default_control_db_url(env: Literal["staging", "prod"]) -> None:
    """env=prod with the default SQLite control_db_url must not boot.

    This mirrors the auth_mode=none-in-prod guard. control_db_url is passed
    explicitly so the test exercises the intended default regardless of an
    ambient HARBORRAG_CONTROL_DB_URL in the environment.
    """
    with pytest.raises(ValueError, match="SQLite is development-only"):
        RuntimeSettings(env=env, control_db_url=DEFAULT_CONTROL_DB_URL)


@pytest.mark.asyncio
@pytest.mark.whitebox
@pytest.mark.parametrize("env", ["staging", "prod"])
async def test_prod_env_rejects_every_explicit_sqlite_url(
    tmp_path: Path, env: Literal["staging", "prod"]
) -> None:
    """An alternate filename must not bypass the production database policy."""
    dsn = f"sqlite+aiosqlite:///{tmp_path}/control.db"
    with pytest.raises(ValueError, match="SQLite is development-only"):
        RuntimeSettings(env=env, control_db_url=dsn)


@pytest.mark.asyncio
@pytest.mark.whitebox
async def test_blank_encryption_key_falls_back_to_the_dev_default(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A whitespace-only key on a SQLite control DB falls back to the dev-default key.

    RuntimeSettings only requires a key for non-SQLite or prod, so the blank
    value is legal at the settings layer. Composition must not derive a Fernet
    key from it and behaves exactly as if the key had been left unset.
    """
    dsn = f"sqlite+aiosqlite:///{tmp_path}/control.db"
    settings = RuntimeSettings(control_db_url=dsn, secrets_encryption_key="   ")

    with caplog.at_level(logging.WARNING, logger="harborrag.runtime.composition"):
        composition = CompositionRoot.production(settings)
    try:
        assert "dev-only default secrets encryption key" in caplog.text
    finally:
        await composition.aclose()


@pytest.mark.asyncio
@pytest.mark.whitebox
async def test_dev_env_allows_default_control_db_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """env=dev keeps booting against the default SQLite control_db_url.

    control_db_url is passed explicitly so the test deterministically
    exercises the intended default regardless of the environment.
    """
    monkeypatch.chdir(tmp_path)
    composition = CompositionRoot.production(
        RuntimeSettings(env="dev", control_db_url=DEFAULT_CONTROL_DB_URL)
    )
    try:
        assert composition.mode == "production"
        assert composition.control_plane is not None
    finally:
        await composition.aclose()


@pytest.mark.whitebox
def test_migration_failure_logs_safe_actionable_diagnostics(
    tmp_path: Path,
    caplog,
) -> None:
    """Failed startup logs a safe cause and an actionable migration hint.

    A schema built without Alembic recording it makes the runner replay from base and
    collide with existing tables. Logging only ``error_type=OperationalError`` leaves no
    way to tell that apart from a connection failure, and the real symptom surfaces much
    later as a missing column in an unrelated query.
    """
    dsn = f"sqlite+aiosqlite:///{tmp_path}/control.db"
    import sqlite3

    connection = sqlite3.connect(f"{tmp_path}/control.db")
    connection.execute("CREATE TABLE projects (id TEXT NOT NULL, PRIMARY KEY (id))")
    connection.commit()
    connection.close()

    with caplog.at_level(logging.ERROR, logger="harborrag.runtime.composition"):
        with pytest.raises(HarborConfigurationError, match="migrations failed"):
            CompositionRoot.production(RuntimeSettings(control_db_url=dsn))

    message = caplog.text
    assert "Control-plane migrations failed" in message
    assert "error_type=OperationalError" in message
    assert "already exists" not in message
    assert "hint=" in message, "the recoverable case must name its remedy"


@pytest.mark.whitebox
def test_database_ahead_of_this_build_names_both_revisions_and_the_remedy(
    tmp_path: Path,
    caplog,
) -> None:
    """Startup against a control DB migrated by a newer build says so and how to recover.

    Starting an older API image against a database a newer branch had migrated reported
    only "migrations failed; inspect the startup logs"; the unknown revision was buried in
    an Alembic traceback and the API crash-looped without naming the cause.
    """
    import sqlite3

    from harborrag_adapters.repositories.database.control_plane.migrations import (
        head_revision,
        run_migrations,
    )

    dsn = f"sqlite+aiosqlite:///{tmp_path}/control.db"
    run_migrations(dsn)
    connection = sqlite3.connect(f"{tmp_path}/control.db")
    connection.execute("UPDATE alembic_version SET version_num = '9999'")
    connection.commit()
    connection.close()
    head = head_revision(dsn)

    with caplog.at_level(logging.ERROR, logger="harborrag.runtime.composition"):
        with pytest.raises(HarborConfigurationError) as caught:
            CompositionRoot.production(RuntimeSettings(control_db_url=dsn))

    message = str(caught.value)
    assert f"schema revision 9999, newer than this build's head {head}" in message
    assert f"downgrade the database to {head}" in message
    assert f"database_revision=9999 build_head={head}" in caplog.text


@pytest.mark.whitebox
@pytest.mark.parametrize("env", ["dev", "prod"])
@pytest.mark.parametrize("key", [None, "   "])
def test_non_sqlite_control_db_refuses_a_blank_encryption_key_before_connecting(
    env: str, key: str | None
) -> None:
    """The dev-default Fernet key never protects secrets in a persistent database.

    This holds in every environment. The check runs before migrations, so this
    unresolvable DSN is never dialled.
    """
    settings = RuntimeSettings(
        env=env,
        control_db_url="postgresql+asyncpg://user:pass@database.invalid/control",
        secrets_encryption_key=key,
    )

    with pytest.raises(
        HarborConfigurationError,
        match="HARBORRAG_SECRETS_ENCRYPTION_KEY or HARBORRAG_SECRETS_ENCRYPTION_KEY_FILE must be set",
    ):
        CompositionRoot.production(settings)


@pytest.mark.whitebox
def test_the_key_file_supplies_the_encryption_key(tmp_path: Path) -> None:
    """A key file supplies the encryption key unless the environment sets one."""
    key_file = tmp_path / "encryption.key"
    key_file.write_text("from-a-mounted-secret\n", encoding="utf-8")
    dsn = "postgresql+asyncpg://user:pass@database.invalid/control"

    from_file = RuntimeSettings(control_db_url=dsn, secrets_encryption_key_file=key_file)
    both = RuntimeSettings(
        control_db_url=dsn, secrets_encryption_key="from-env", secrets_encryption_key_file=key_file
    )

    assert secrets_encryption_key(from_file) == "from-a-mounted-secret"
    assert secrets_encryption_key(both) == "from-env"
    key_file.write_text("\n", encoding="utf-8")
    with pytest.raises(HarborConfigurationError, match="is empty"):
        secrets_encryption_key(from_file)
    with pytest.raises(HarborConfigurationError, match="cannot be read"):
        secrets_encryption_key(
            RuntimeSettings(control_db_url=dsn, secrets_encryption_key_file=tmp_path / "missing")
        )


@pytest.mark.whitebox
def test_production_composition_exposes_config_store(tmp_path: Path) -> None:
    """With SQLite the provider polls only: it is built without a change feed."""
    from harborrag_adapters.repositories.database.control_plane.config_store import (
        SqlSettingsStore,
    )
    from harborrag_runtime.config_store import CachedConfigProvider

    control_plane = _production(tmp_path).control_plane

    assert control_plane is not None
    assert isinstance(control_plane.config_store, SqlSettingsStore)
    assert isinstance(control_plane.config, CachedConfigProvider)
    assert control_plane.config.has_feed is False
