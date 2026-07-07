from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class McpToolPolicy:
    max_results: int = 20
    allow_ingestion: bool = False

    def check_results(self, count: int) -> None:
        if count > self.max_results:
            raise ValueError("MCP result budget exceeded.")
