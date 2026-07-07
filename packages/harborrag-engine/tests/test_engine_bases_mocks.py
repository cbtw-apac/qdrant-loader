from __future__ import annotations

import pytest
from harborrag_adapters.connectors.mock import MockConnector
from harborrag_adapters.parsers.mock import MockMarkdownParser
from harborrag_core.domain.document import HarborDocument
from harborrag_core.domain.graph import GraphHint
from harborrag_core.domain.metadata import DocumentMetadata
from harborrag_core.domain.provenance import DocumentProvenance
from harborrag_core.domain.raw_document import RawDocument
from harborrag_core.domain.retrieval import RetrievalQuery, RetrievalResult
from harborrag_engine.builder import EngineBuilder
from harborrag_engine.config import EngineConfig
from harborrag_engine.graph.base import BaseGraphMapper
from harborrag_engine.graph.mock import MockGraphMapper
from harborrag_engine.indexing.base import BaseIndexer
from harborrag_engine.indexing.mock import MockIndexer
from harborrag_engine.ingestion.base import (
    BaseChunker,
    BaseDocumentNormalizer,
    BaseIngestionPipeline,
)
from harborrag_engine.ingestion.mock import (
    MockChunker,
    MockDocumentNormalizer,
    MockIngestionPipeline,
)
from harborrag_engine.policy import EnginePolicy
from harborrag_engine.retrieval.base import BaseEvidenceBuilder, BaseRetrievalPipeline
from harborrag_engine.retrieval.fusion import reciprocal_rank_fusion
from harborrag_engine.retrieval.mock import MockEvidenceBuilder, MockRetrievalPipeline
from harborrag_engine.retrieval.reranking import keep_top
from harborrag_engine.retrieval.rewriting import identity_rewrite


def make_doc() -> HarborDocument:
    hint = GraphHint("doc", "mentions", "user:alice", "Document", "User")
    return HarborDocument(
        "doc",
        "memory://doc",
        "mock",
        "text/plain",
        "Doc",
        "hello harbor rag",
        DocumentMetadata("doc", "mock"),
        DocumentProvenance("mock", "mock"),
        graph_hints=[hint],
    )


class BrokenNormalizer(BaseDocumentNormalizer):
    def normalize(self, raw, parsed_text):
        return super().normalize(raw, parsed_text)


class BrokenChunker(BaseChunker):
    def chunk(self, document):
        return super().chunk(document)


class BrokenIngestion(BaseIngestionPipeline):
    def run_once(self):
        return super().run_once()

    def summarize(self):
        return super().summarize()


class BrokenRetrieval(BaseRetrievalPipeline):
    def retrieve(self, query):
        return super().retrieve(query)


class BrokenEvidence(BaseEvidenceBuilder):
    def build(self, results):
        return super().build(results)


class BrokenIndexer(BaseIndexer):
    def index(self, documents):
        return super().index(documents)


class BrokenGraphMapper(BaseGraphMapper):
    def map_document(self, document):
        return super().map_document(document)


def test_base_methods_raise():
    raw = RawDocument("doc", "src", "text", "text/plain")
    doc = make_doc()
    with pytest.raises(NotImplementedError):
        BrokenNormalizer().normalize(raw, "text")
    with pytest.raises(NotImplementedError):
        BrokenChunker().chunk(doc)
    with pytest.raises(NotImplementedError):
        BrokenIngestion().run_once()
    with pytest.raises(NotImplementedError):
        BrokenIngestion().summarize()
    with pytest.raises(NotImplementedError):
        BrokenRetrieval().retrieve(RetrievalQuery("q"))
    with pytest.raises(NotImplementedError):
        BrokenEvidence().build([])
    with pytest.raises(NotImplementedError):
        BrokenIndexer().index([doc])
    with pytest.raises(NotImplementedError):
        BrokenGraphMapper().map_document(doc)


def test_mock_ingestion_chunking_indexing_graph_and_builder():
    pipeline = MockIngestionPipeline(
        MockConnector(), MockMarkdownParser(), MockDocumentNormalizer(), MockChunker()
    )
    docs = pipeline.run_once()
    assert docs[0].title == "Mock Document"
    assert pipeline.summarize().parsed == 1
    assert MockChunker().chunk(docs[0])
    indexer = MockIndexer(indexed=[])
    assert indexer.index(docs) == 1
    assert indexer.indexed == [docs[0].id]
    assert MockGraphMapper().map_document(docs[0]) == docs[0].graph_hints
    diagnostics = EngineBuilder(
        EngineConfig(tenant="t", environment="test"), EnginePolicy(max_concurrency=2)
    ).diagnostics()
    assert diagnostics["tenant"] == "t"
    with pytest.raises(ValueError):
        EnginePolicy(max_concurrency=0)


def test_mock_retrieval_evidence_fusion_rewrite_rerank():
    results = [
        RetrievalResult("a", "harbor rag", 0.1),
        RetrievalResult("b", "other", 0.9),
    ]
    retrieved = MockRetrievalPipeline(results).retrieve(
        RetrievalQuery("harbor", top_k=2)
    )
    assert retrieved[0].id == "a"
    assert "[1]" in MockEvidenceBuilder().build(retrieved)
    fused = reciprocal_rank_fusion([[results[0], results[1]], [results[1]]])
    assert fused[0].id == "b"
    assert identity_rewrite("hello") == ["hello"]
    assert keep_top(results, 1)[0].id == "b"
