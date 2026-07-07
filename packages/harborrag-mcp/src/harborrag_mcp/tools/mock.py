from __future__ import annotations

from dataclasses import asdict, dataclass, field

from harborrag_core.domain.retrieval import RetrievalQuery, RetrievalResult
from harborrag_engine.retrieval.mock import MockRetrievalPipeline
from harborrag_runtime.composition import CompositionRoot

from harborrag_mcp.tools.base import BaseMcpTool, McpToolSpec


class MockHealthTool(BaseMcpTool):
    spec = McpToolSpec("harbor_health_check", "Return HarborRAG health diagnostics.")

    def call(self, arguments: dict[str, object]) -> dict[str, object]:
        return {"ok": True, "diagnostics": CompositionRoot.local().diagnostics()}


@dataclass(slots=True)
class MockRetrieveTool(BaseMcpTool):
    pipeline: MockRetrievalPipeline = field(
        default_factory=lambda: MockRetrievalPipeline(
            [RetrievalResult("doc", "HarborRAG mock result", 1.0)]
        )
    )
    spec = McpToolSpec(
        "harbor_sample_retrieve",
        "Retrieve from a deterministic mock result set.",
        {"type": "object", "properties": {"query": {"type": "string"}}},
    )

    def call(self, arguments: dict[str, object]) -> dict[str, object]:
        query = str(arguments.get("query", "HarborRAG"))
        return {
            "ok": True,
            "results": [
                asdict(r) for r in self.pipeline.retrieve(RetrievalQuery(query))
            ],
        }
