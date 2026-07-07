from dataclasses import dataclass, field
from typing import Literal

JobStatus = Literal["queued", "running", "succeeded", "failed"]


@dataclass(slots=True)
class JobState:
    id: str
    status: JobStatus = "queued"
    error: str | None = None


@dataclass(slots=True)
class InMemoryJobStore:
    jobs: dict[str, JobState] = field(default_factory=dict)

    def save(self, job: JobState) -> None:
        self.jobs[job.id] = job

    def get(self, job_id: str) -> JobState | None:
        return self.jobs.get(job_id)
