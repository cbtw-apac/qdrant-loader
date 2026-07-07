from dataclasses import dataclass, field


@dataclass(slots=True)
class McpAuditLog:
    entries: list[dict[str, object]] = field(default_factory=list)

    def record(self, tool: str) -> None:
        self.entries.append({"tool": tool})
