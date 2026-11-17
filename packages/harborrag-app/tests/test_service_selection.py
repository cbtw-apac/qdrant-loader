"""Application-service selection uses the configured durable composition."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from harborrag_app.api.app import create_fastapi_app
from harborrag_app.api.settings import ApiSettings
from harborrag_app.workflow_control.composition.selection import select_app_service
from harborrag_app.workflow_control.composition.service import AppService
from harborrag_runtime.config import ParserConfigurationError

_SELECTION_LOGGER = "harborrag.app.workflow_control.composition.selection"

_EMPTY_BACKEND_CATALOG = """\
version: 1
parsers:
  custom-pdf:
    parser: pdf
    engines:
      - backend: ""
"""

_OTHER_BACKEND_SETTINGS_CATALOG = """\
version: 1
parsers:
  custom-pdf:
    parser: pdf
    engines:
      - backend: docling
        settings:
          do_ocr: true
          num_workers: 3
          output_format: markdown
"""


def _use_parser_catalog(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, content: str) -> None:
    """Point a dev runtime at a parser catalog file holding ``content``."""
    catalog_path = tmp_path / "parsers.yaml"
    catalog_path.write_text(content, encoding="utf-8")
    monkeypatch.setenv("HARBORRAG_ENV", "dev")
    monkeypatch.setenv("HARBORRAG_CONTROL_DB_URL", f"sqlite+aiosqlite:///{tmp_path}/control.db")
    monkeypatch.setenv("HARBORRAG_PARSER_CONFIG_PATH", str(catalog_path))


@pytest.mark.blackbox
def test_dev_without_explicit_control_db_uses_default_sqlite(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Bare development provisions the default durable SQLite control plane."""
    monkeypatch.setenv("HARBORRAG_ENV", "dev")
    monkeypatch.delenv("HARBORRAG_CONTROL_DB_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    service, mode = select_app_service()
    assert isinstance(service, AppService)
    assert mode == "production"
    diagnostics = service.health().data["diagnostics"]
    assert diagnostics["mode"] == "production"
    assert diagnostics["runtime"]["control_db"]["scheme"] == "sqlite+aiosqlite"


@pytest.mark.blackbox
def test_control_db_url_selects_production(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Compose a migrated, healthy production service from a control DB URL."""
    monkeypatch.setenv("HARBORRAG_ENV", "dev")
    monkeypatch.setenv("HARBORRAG_CONTROL_DB_URL", f"sqlite+aiosqlite:///{tmp_path}/control.db")
    service, mode = select_app_service()
    assert isinstance(service, AppService)
    assert mode == "production"
    health = service.health()
    assert health.ok is True


@pytest.mark.blackbox
def test_api_boots_production_composition_end_to_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Factory lifespan composes production while operational routes stay small."""
    monkeypatch.setenv("HARBORRAG_ENV", "dev")
    monkeypatch.setenv("HARBORRAG_CONTROL_DB_URL", f"sqlite+aiosqlite:///{tmp_path}/control.db")
    with TestClient(create_fastapi_app(ApiSettings())) as client:
        assert client.get("/healthz").status_code == 200
        assert client.app.state.composition_mode == "production"
        assert client.app.state.app_service.health().ok is True


@pytest.mark.blackbox
def test_select_app_service_empty_parser_backend_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _use_parser_catalog(monkeypatch, tmp_path, _EMPTY_BACKEND_CATALOG)

    with pytest.raises(ParserConfigurationError, match="parser 'custom-pdf' engine 0"):
        select_app_service()

    assert not (tmp_path / "control.db").exists(), "rejected before the control plane is touched"


@pytest.mark.blackbox
def test_select_app_service_missing_parser_catalog_is_logged(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    missing_catalog = tmp_path / "parsers.yaml"
    monkeypatch.setenv("HARBORRAG_ENV", "dev")
    monkeypatch.setenv("HARBORRAG_CONTROL_DB_URL", f"sqlite+aiosqlite:///{tmp_path}/control.db")
    monkeypatch.setenv("HARBORRAG_PARSER_CONFIG_PATH", str(missing_catalog))

    with caplog.at_level(logging.WARNING, logger=_SELECTION_LOGGER):
        select_app_service()

    warnings = [
        record.getMessage()
        for record in caplog.records
        if record.name == _SELECTION_LOGGER and record.levelno == logging.WARNING
    ]
    assert len(warnings) == 1
    assert str(missing_catalog) in warnings[0]


@pytest.mark.blackbox
@pytest.mark.parametrize(
    ("catalog", "named_in_error"),
    [
        pytest.param(
            _EMPTY_BACKEND_CATALOG,
            ("'custom-pdf'", "non-empty backend", "docling", "liteparse"),
            id="empty-backend",
        ),
        pytest.param(
            _OTHER_BACKEND_SETTINGS_CATALOG,
            ("'custom-pdf'", "docling", "num_workers", "output_format"),
            id="settings-of-another-backend",
        ),
    ],
)
def test_api_startup_invalid_parser_catalog_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    catalog: str,
    named_in_error: tuple[str, ...],
) -> None:
    _use_parser_catalog(monkeypatch, tmp_path, catalog)

    with (
        pytest.raises(ParserConfigurationError) as error,
        TestClient(create_fastapi_app(ApiSettings())),
    ):
        pytest.fail("the API started with an invalid parser catalog")

    message = str(error.value)
    assert [name for name in named_in_error if name not in message] == []
