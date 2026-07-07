from dataclasses import dataclass


@dataclass(slots=True)
class CapabilityBudget:
    max_documents: int = 1000
    max_bytes: int = 50_000_000
    max_tool_calls: int = 20

    def check_documents(self, count: int) -> None:
        if count > self.max_documents:
            raise ValueError(
                f"Document budget exceeded: {count} > {self.max_documents}"
            )
