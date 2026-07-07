from __future__ import annotations

from abc import ABC, abstractmethod

from harborrag_runtime.job_state import JobState


class BaseJobStore(ABC):
    """Persist job state.

    TODO: Implement durable stores for SQLite/PostgreSQL/MongoDB/Redis and add optimistic
    concurrency checks so workers cannot overwrite each other's job state.
    """

    @abstractmethod
    def save(self, job: JobState) -> None:
        raise NotImplementedError

    @abstractmethod
    def get(self, job_id: str) -> JobState | None:
        raise NotImplementedError
