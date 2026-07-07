from __future__ import annotations

import json

import pytest
from harborrag_app.api.app import create_app_state
from harborrag_app.api.base import BaseApiController
from harborrag_app.api.dependencies import get_app_service
from harborrag_app.api.mock import MockApiController
from harborrag_app.cli.base import BaseCliCommand
from harborrag_app.cli.main import main
from harborrag_app.cli.mock import MockDoctorCommand
from harborrag_app.services.base import BaseAppService
from harborrag_app.services.mock import MockAppService


class BrokenService(BaseAppService):
    def health(self):
        return super().health()

    def ingest_once(self):
        return super().ingest_once()


class BrokenCli(BaseCliCommand):
    name = "broken"

    def run(self, *, as_json=False):
        return super().run(as_json=as_json)


class BrokenController(BaseApiController):
    def register(self):
        return super().register()


def test_app_base_methods_raise():
    with pytest.raises(NotImplementedError):
        BrokenService().health()
    with pytest.raises(NotImplementedError):
        BrokenService().ingest_once()
    with pytest.raises(NotImplementedError):
        BrokenCli().run()
    with pytest.raises(NotImplementedError):
        BrokenController().register()


def test_app_mocks_and_cli_outputs(capsys):
    service = MockAppService()
    assert service.health().ok is True
    ingest = service.ingest_once()
    assert ingest.ok and ingest.data["documents"]
    assert get_app_service().health().ok
    assert create_app_state()["service"]["diagnostics"]["runtime"]["ready"] is True
    assert MockApiController("health").register()["controller"] == "health"
    assert MockDoctorCommand(service).run(as_json=True) == 0
    doctor_payload = json.loads(capsys.readouterr().out)
    assert doctor_payload["ok"] is True
    assert main(["doctor", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert main(["sample-ingest", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
