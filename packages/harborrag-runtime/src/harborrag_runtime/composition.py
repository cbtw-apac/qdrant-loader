from __future__ import annotations

from dataclasses import dataclass, field

from harborrag_adapters.connectors.mock import MockConnector
from harborrag_adapters.models.embedding.mock import MockEmbeddingModel
from harborrag_adapters.parsers.mock import MockMarkdownParser
from harborrag_adapters.repositories.vector.mock import MockVectorRepository
from harborrag_engine.builder import EngineBuilder
from harborrag_engine.ingestion.mock import MockIngestionPipeline

from harborrag_runtime.services.base import BaseRuntimeService
from harborrag_runtime.services.mock import MockRuntimeService


@dataclass(slots=True)
class CompositionRoot:
    engine_builder: EngineBuilder
    runtime_service: BaseRuntimeService = field(default_factory=MockRuntimeService)

    @classmethod
    def local(cls) -> CompositionRoot:
        return cls(engine_builder=EngineBuilder())

    def mock_pipeline(self) -> MockIngestionPipeline:
        """Build deterministic local pipeline from co-located base/mock packages.

        TODO: Replace this hard-coded assembly with configuration-driven composition that
        validates provider names, required secrets, repository settings, and feature budgets.
        """
        return MockIngestionPipeline(
            MockConnector(),
            MockMarkdownParser(),
            embedder=MockEmbeddingModel(),
            vector_repository=MockVectorRepository(),
        )

    def sample_pipeline(self) -> MockIngestionPipeline:
        """Build a sample pipeline that ingests a small set of documents for testing and demonstration.

        TODO: Implement a sample pipeline that ingests a small set of documents for testing and demonstration.
        """
        return self.mock_pipeline()

    def diagnostics(self) -> dict[str, object]:
        return {
            "runtime": self.runtime_service.diagnostics(),
            "engine": self.engine_builder.diagnostics(),
        }

    def run_mock_ingestion(self) -> dict[str, object]:
        """Run a mock ingestion pipeline that ingests a small set of documents for testing and demonstration.

        TODO: Implement a mock ingestion pipeline that ingests a small set of documents for testing and demonstration.
        """
        return self.runtime_service.run_mock_ingestion()
