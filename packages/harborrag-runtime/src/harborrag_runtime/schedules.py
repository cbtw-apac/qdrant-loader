from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ScheduleSpec:
    name: str
    cron: str
