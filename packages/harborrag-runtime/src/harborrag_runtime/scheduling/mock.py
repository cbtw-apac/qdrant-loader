from __future__ import annotations

from dataclasses import dataclass, field

from harborrag_runtime.schedules import ScheduleSpec
from harborrag_runtime.scheduling.base import BaseScheduler


@dataclass(slots=True)
class MockScheduler(BaseScheduler):
    schedules: list[ScheduleSpec] = field(default_factory=list)

    def add(self, schedule: ScheduleSpec) -> None:
        self.schedules.append(schedule)
