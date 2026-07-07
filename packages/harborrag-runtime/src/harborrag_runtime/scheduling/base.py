from __future__ import annotations

from abc import ABC, abstractmethod

from harborrag_runtime.schedules import ScheduleSpec


class BaseScheduler(ABC):
    """Manage scheduled jobs.

    TODO: Implement store-backed schedules, missed-run handling, and integration with the
    runtime supervisor or Temporal workflow launcher.
    """

    @abstractmethod
    def add(self, schedule: ScheduleSpec) -> None:
        raise NotImplementedError
