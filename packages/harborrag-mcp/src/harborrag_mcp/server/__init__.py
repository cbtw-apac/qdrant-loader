from __future__ import annotations

from typing import Any

from harborrag_mcp.server.base import BaseMcpServer
from harborrag_mcp.server.mock import MockMcpServer


def list_tools() -> list[dict[str, object]]:
    return [
        {"name": s.name, "description": s.description, "input_schema": s.input_schema}
        for s in MockMcpServer().list_tools()
    ]


def call_tool(
    name: str, arguments: dict[str, object] | None = None, **kwargs: Any
) -> dict[str, object]:
    payload = dict(arguments or {})
    payload.update(kwargs)
    return MockMcpServer().call_tool(name, payload)


__all__ = ["BaseMcpServer", "MockMcpServer", "call_tool", "list_tools"]
