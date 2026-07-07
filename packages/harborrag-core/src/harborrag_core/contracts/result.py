from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Result[T]:
    value: T | None = None
    error: Exception | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @classmethod
    def success(cls, value: T) -> Result[T]:
        return cls(value=value)

    @classmethod
    def failure(cls, error: Exception) -> Result[T]:
        return cls(error=error)

    def unwrap(self) -> T:
        if self.error is not None:
            raise self.error
        if self.value is None:
            raise ValueError("Result has no value.")
        return self.value
