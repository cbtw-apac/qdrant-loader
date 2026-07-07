from __future__ import annotations

from dataclasses import dataclass

from harborrag_app.api.base import BaseApiController


@dataclass(slots=True)
class MockApiController(BaseApiController):
    name: str = "mock"

    def register(self) -> dict[str, object]:
        return {"controller": self.name, "registered": True}
