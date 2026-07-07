from __future__ import annotations

from dataclasses import dataclass, field

from harborrag_adapters.repositories.object_store.base import BaseObjectRepository


@dataclass(slots=True)
class MockObjectRepository(BaseObjectRepository):
    provider_name: str = "mock_object"
    values: dict[str, bytes] = field(default_factory=dict)

    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> str:
        self.values[key] = data
        return f"memory://{key}"

    def get_bytes(self, key: str) -> bytes:
        return self.values[key]
