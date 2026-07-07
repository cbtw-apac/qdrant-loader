from __future__ import annotations

from dataclasses import dataclass, field

from harborrag_runtime.job_state import JobState
from harborrag_runtime.jobs.base import BaseJobStore


@dataclass(slots=True)
class MockJobStore(BaseJobStore):
    jobs: dict[str, JobState] = field(default_factory=dict)

    def save(self, job: JobState) -> None:
        self.jobs[job.id] = job

    def get(self, job_id: str) -> JobState | None:
        return self.jobs.get(job_id)
