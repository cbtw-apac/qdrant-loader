from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class McpToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=lambda: {"type": "object"})


class BaseMcpTool(ABC):
    """Base class for MCP tools.

    TODO: Implement service-only tools that enforce identity, tenant, capability budgets,
    input validation, audit logging, and permission checks before calling runtime services.
    """

    spec: McpToolSpec

    @abstractmethod
    def call(self, arguments: dict[str, object]) -> dict[str, object]:
        raise NotImplementedError
