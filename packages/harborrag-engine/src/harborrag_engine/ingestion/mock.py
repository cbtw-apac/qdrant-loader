from __future__ import annotations

from dataclasses import dataclass, field

from harborrag_adapters.connectors.base import BaseConnector
from harborrag_adapters.models.embedding.base import BaseEmbeddingModel
from harborrag_adapters.parsers.base import BaseParser
from harborrag_adapters.repositories.vector.base import BaseVectorRepository
from harborrag_core.domain.document import HarborDocument
from harborrag_core.domain.element import DocumentElement
from harborrag_core.domain.metadata import DocumentMetadata
from harborrag_core.domain.parsed_document import ParsedDocument
from harborrag_core.domain.provenance import DocumentProvenance
from harborrag_core.domain.raw_document import RawDocument

from harborrag_engine.ingestion.base import (
    BaseChunker,
    BaseDocumentNormalizer,
    BaseIngestionPipeline,
    IngestionRunSummary,
)


class MockDocumentNormalizer(BaseDocumentNormalizer):
    def normalize(self, raw: RawDocument, parsed_text: str) -> HarborDocument:
        return HarborDocument(
            id=raw.id,
            source=raw.source,
            source_type=str(raw.metadata.get("source_type", "mock")),
            content_type=raw.content_type,
            title=str(raw.metadata.get("title", raw.id)),
            text=parsed_text,
            metadata=DocumentMetadata(source_id=raw.id, source_system="mock"),
            provenance=DocumentProvenance(connector_name="mock", parser_name="mock"),
            elements=[
                DocumentElement(id=f"{raw.id}:0", type="paragraph", text=parsed_text)
            ],
        )


class MockChunker(BaseChunker):
    def __init__(self, chunk_size: int = 200) -> None:
        self.chunk_size = chunk_size

    def chunk(self, document: HarborDocument) -> list[str]:
        return [
            document.text[i : i + self.chunk_size]
            for i in range(0, len(document.text), self.chunk_size)
        ] or [""]


@dataclass(slots=True)
class MockIngestionPipeline(BaseIngestionPipeline):
    connector: BaseConnector
    parser: BaseParser
    normalizer: BaseDocumentNormalizer = field(default_factory=MockDocumentNormalizer)
    embedder: BaseEmbeddingModel | None = None
    vector_repository: BaseVectorRepository | None = None
    _last_summary: IngestionRunSummary = field(
        default_factory=lambda: IngestionRunSummary(0, 0, 0, 0)
    )

    def run_once(self) -> list[HarborDocument]:
        documents: list[HarborDocument] = []
        discovered = loaded = parsed_count = indexed = 0
        for record in self.connector.discover():
            discovered += 1
            raw = self.connector.load(record)
            loaded += 1
            parsed: ParsedDocument = self.parser.parse(raw)
            parsed_count += 1
            documents.append(self.normalizer.normalize(raw, parsed.text))
        if self.embedder and self.vector_repository and documents:
            vectors = self.embedder.embed([doc.text for doc in documents]).vectors
            self.vector_repository.upsert(
                [
                    {
                        "id": doc.id,
                        "text": doc.text,
                        "vector": vector,
                        "metadata": doc.vector_payload(),
                    }
                    for doc, vector in zip(documents, vectors, strict=True)
                ]
            )
            indexed = len(documents)
        self._last_summary = IngestionRunSummary(
            discovered, loaded, parsed_count, indexed
        )
        return documents

    def summarize(self) -> IngestionRunSummary:
        return self._last_summary
