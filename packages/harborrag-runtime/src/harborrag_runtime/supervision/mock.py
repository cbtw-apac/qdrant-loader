from __future__ import annotations

from dataclasses import dataclass, field

from harborrag_runtime.supervision.base import BaseSupervisor


@dataclass(slots=True)
class MockSupervisor(BaseSupervisor):
    submitted: list[str] = field(default_factory=list)

    def submit(self, job_id: str) -> None:
        self.submitted.append(job_id)
