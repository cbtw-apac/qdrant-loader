from __future__ import annotations

from dataclasses import dataclass
from time import monotonic

from harborrag_core.contracts.errors import HarborDeadlineExceeded


@dataclass(slots=True)
class Deadline:
    timeout_seconds: float | None
    started_at: float = 0.0

    def __post_init__(self) -> None:
        if self.started_at == 0.0:
            self.started_at = monotonic()

    def remaining(self) -> float | None:
        if self.timeout_seconds is None:
            return None
        return max(0.0, self.timeout_seconds - (monotonic() - self.started_at))

    def check(self) -> None:
        rem = self.remaining()
        if rem is not None and rem <= 0:
            raise HarborDeadlineExceeded("Deadline exceeded.")
