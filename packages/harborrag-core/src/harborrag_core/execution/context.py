from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from harborrag_core.domain.tenant import Tenant


@dataclass(frozen=True, slots=True)
class RequestContext:
    trace_id: str = field(default_factory=lambda: uuid4().hex)
    tenant: Tenant = field(default_factory=Tenant)
    deadline_seconds: float | None = None

    def child(self) -> RequestContext:
        return RequestContext(
            trace_id=self.trace_id,
            tenant=self.tenant,
            deadline_seconds=self.deadline_seconds,
        )
