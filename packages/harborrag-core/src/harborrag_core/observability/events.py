from __future__ import annotations

from dataclasses import dataclass, field

from harborrag_core.contracts.events import HarborEvent


@dataclass(slots=True)
class InMemoryEventBus:
    events: list[HarborEvent] = field(default_factory=list)

    def publish(self, event: HarborEvent) -> None:
        self.events.append(event)
