from __future__ import annotations

import json
from dataclasses import dataclass

from harborrag_app.cli.base import BaseCliCommand
from harborrag_app.services.base import BaseAppService
from harborrag_app.services.mock import MockAppService


@dataclass(slots=True)
class MockDoctorCommand(BaseCliCommand):
    service: BaseAppService = MockAppService()
    name: str = "doctor"

    def run(self, *, as_json: bool = False) -> int:
        response = self.service.health()
        payload = {"ok": response.ok, **response.data}
        print(json.dumps(payload, sort_keys=True) if as_json else payload)
        return 0
