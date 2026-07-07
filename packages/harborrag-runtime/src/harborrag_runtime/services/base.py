from __future__ import annotations

from abc import ABC, abstractmethod


class BaseRuntimeService(ABC):
    """Runtime service facade used by app and MCP layers.

    TODO: Implement methods through validated configuration, job state, supervisor, schedules,
    and engine pipelines. Do not expose raw adapter clients through this service.
    """

    @abstractmethod
    def diagnostics(self) -> dict[str, object]:
        raise NotImplementedError

    @abstractmethod
    def run_mock_ingestion(self) -> dict[str, object]:
        raise NotImplementedError
