from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AppResponse:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class BaseAppService(ABC):
    """Application service facade for HTTP and CLI.

    TODO: Implement production service methods with request context, auth/permission checks,
    input validation, structured error envelopes, and fail-closed defaults.
    """

    @abstractmethod
    def health(self) -> AppResponse:
        raise NotImplementedError

    @abstractmethod
    def ingest_once(self) -> AppResponse:
        raise NotImplementedError
