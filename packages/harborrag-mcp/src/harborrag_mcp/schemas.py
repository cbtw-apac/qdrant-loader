def tool_schema(name: str, description: str) -> dict[str, object]:
    return {"name": name, "description": description, "inputSchema": {"type": "object"}}
