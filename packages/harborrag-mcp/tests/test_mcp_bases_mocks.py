from __future__ import annotations

import pytest
from harborrag_mcp.server import call_tool, list_tools
from harborrag_mcp.server.base import BaseMcpServer
from harborrag_mcp.server.mock import MockMcpServer
from harborrag_mcp.tools.base import BaseMcpTool, McpToolSpec
from harborrag_mcp.tools.mock import MockHealthTool, MockRetrieveTool


class BrokenTool(BaseMcpTool):
    spec = McpToolSpec("broken", "broken")

    def call(self, arguments):
        return super().call(arguments)


class BrokenServer(BaseMcpServer):
    def list_tools(self):
        return super().list_tools()

    def call_tool(self, name, arguments=None):
        return super().call_tool(name, arguments)


def test_mcp_base_methods_raise():
    with pytest.raises(NotImplementedError):
        BrokenTool().call({})
    with pytest.raises(NotImplementedError):
        BrokenServer().list_tools()
    with pytest.raises(NotImplementedError):
        BrokenServer().call_tool("x")


def test_mcp_mock_tools_server_and_module_facade():
    spec = McpToolSpec("tool", "description")
    assert spec.input_schema == {"type": "object"}
    health = MockHealthTool().call({})
    assert health["ok"] is True
    retrieve = MockRetrieveTool().call({"query": "HarborRAG"})
    assert retrieve["results"][0]["id"] == "doc"
    server = MockMcpServer()
    assert [tool.name for tool in server.list_tools()] == [
        "harbor_health_check",
        "harbor_sample_retrieve",
    ]
    assert server.call_tool("harbor_health_check")["ok"] is True
    with pytest.raises(ValueError):
        server.call_tool("missing")
    assert list_tools()[0]["name"] == "harbor_health_check"
    assert call_tool("harbor_sample_retrieve", {"query": "rag"})["ok"] is True
    with pytest.raises(ValueError):
        call_tool("missing")
