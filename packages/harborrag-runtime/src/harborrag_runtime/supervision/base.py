from __future__ import annotations

from abc import ABC, abstractmethod


class BaseSupervisor(ABC):
    """Run bounded local workers.

    TODO: Implement queueing, worker limits, cancellation, timeouts, and structured job logs.
    """

    @abstractmethod
    def submit(self, job_id: str) -> None:
        raise NotImplementedError
