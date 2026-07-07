from __future__ import annotations

from dataclasses import dataclass, field

from harborrag_mcp.server.base import BaseMcpServer
from harborrag_mcp.tools.base import BaseMcpTool, McpToolSpec
from harborrag_mcp.tools.mock import MockHealthTool, MockRetrieveTool


@dataclass(slots=True)
class MockMcpServer(BaseMcpServer):
    tools: list[BaseMcpTool] = field(
        default_factory=lambda: [MockHealthTool(), MockRetrieveTool()]
    )

    def list_tools(self) -> list[McpToolSpec]:
        return [tool.spec for tool in self.tools]

    def call_tool(
        self, name: str, arguments: dict[str, object] | None = None
    ) -> dict[str, object]:
        for tool in self.tools:
            if tool.spec.name == name:
                return tool.call(arguments or {})
        raise ValueError(f"Unknown MCP tool: {name}")
