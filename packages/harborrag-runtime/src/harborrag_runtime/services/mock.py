from __future__ import annotations

from dataclasses import asdict

from harborrag_runtime.services.base import BaseRuntimeService


class MockRuntimeService(BaseRuntimeService):
    def diagnostics(self) -> dict[str, object]:
        return {"provider": "mock_runtime", "ready": True}

    def run_mock_ingestion(self) -> dict[str, object]:

        from harborrag_runtime.composition import CompositionRoot

        pipeline = CompositionRoot.local().mock_pipeline()
        docs = pipeline.run_once()
        summary = pipeline.summarize()

        return {"documents": [doc.id for doc in docs], "summary": asdict(summary)}
