from dataclasses import dataclass, field


@dataclass(slots=True)
class LocalSupervisor:
    running_jobs: set[str] = field(default_factory=set)

    def start(self, job_id: str) -> None:
        self.running_jobs.add(job_id)

    def finish(self, job_id: str) -> None:
        self.running_jobs.discard(job_id)
