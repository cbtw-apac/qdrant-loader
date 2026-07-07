from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class InMemoryMetrics:
    counters: dict[str, int] = field(default_factory=dict)
    observations: dict[str, list[float]] = field(default_factory=dict)

    def increment(self, name: str, value: int = 1, **labels: str) -> None:
        self.counters[_key(name, labels)] = (
            self.counters.get(_key(name, labels), 0) + value
        )

    def observe(self, name: str, value: float, **labels: str) -> None:
        self.observations.setdefault(_key(name, labels), []).append(value)


def _key(name: str, labels: dict[str, str]) -> str:
    return (
        name
        if not labels
        else name + "{" + ",".join(f"{k}={v}" for k, v in sorted(labels.items())) + "}"
    )
