from __future__ import annotations

from abc import ABC, abstractmethod

from harborrag_mcp.tools.base import McpToolSpec


class BaseMcpServer(ABC):
    """Base class for an MCP server transport.

    TODO: Implement the real MCP transport by exposing only BaseMcpTool instances, adding audit
    logs for every call, and rejecting raw database/provider operations.
    """

    @abstractmethod
    def list_tools(self) -> list[McpToolSpec]:
        raise NotImplementedError

    @abstractmethod
    def call_tool(
        self, name: str, arguments: dict[str, object] | None = None
    ) -> dict[str, object]:
        raise NotImplementedError
