from __future__ import annotations

from abc import ABC, abstractmethod


class BaseObjectRepository(ABC):
    """Base class for object repositories.

    TODO: Implement real repositories with metadata, content type, checksums, safe key policy,
    multipart upload if supported, and local/cloud parity tests.
    """

    provider_name: str

    @abstractmethod
    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> str:
        raise NotImplementedError

    @abstractmethod
    def get_bytes(self, key: str) -> bytes:
        raise NotImplementedError
