from __future__ import annotations

from pathlib import Path

import pytest
from harborrag_adapters.builder import AdapterBuilder
from harborrag_adapters.connectors.base import BaseConnector
from harborrag_adapters.connectors.mock import MockConnector, MockLocalTextFileConnector
from harborrag_adapters.models.chat.base import BaseChatModel
from harborrag_adapters.models.chat.mock import MockChatModel
from harborrag_adapters.models.embedding.base import BaseEmbeddingModel
from harborrag_adapters.models.embedding.mock import MockEmbeddingModel
from harborrag_adapters.models.reranker.base import BaseReranker
from harborrag_adapters.models.reranker.mock import MockReranker
from harborrag_adapters.parsers.base import BaseParser
from harborrag_adapters.parsers.mock import MockMarkdownParser
from harborrag_adapters.registry import AdapterRegistry
from harborrag_adapters.repositories.cache.base import BaseCacheRepository
from harborrag_adapters.repositories.cache.mock import MockCacheRepository
from harborrag_adapters.repositories.database.base import BaseDatabaseRepository
from harborrag_adapters.repositories.database.mock import MockDatabaseRepository
from harborrag_adapters.repositories.graph.base import BaseGraphRepository
from harborrag_adapters.repositories.graph.mock import MockGraphRepository
from harborrag_adapters.repositories.object_store.base import BaseObjectRepository
from harborrag_adapters.repositories.object_store.mock import MockObjectRepository
from harborrag_adapters.repositories.vector.base import BaseVectorRepository
from harborrag_adapters.repositories.vector.mock import MockVectorRepository
from harborrag_core.domain.graph import GraphHint
from harborrag_core.domain.raw_document import RawDocument
from harborrag_core.domain.source import SourceRecord


class BrokenConnector(BaseConnector):
    provider_name = "broken"

    def discover(self):
        return super().discover()

    def load(self, record):
        return super().load(record)


class BrokenParser(BaseParser):
    parser_name = "broken"

    def parse(self, raw):
        return super().parse(raw)


class BrokenChat(BaseChatModel):
    provider_name = "broken"

    def respond(self, messages):
        return super().respond(messages)


class BrokenEmbedding(BaseEmbeddingModel):
    provider_name = "broken"

    def embed(self, texts):
        return super().embed(texts)


class BrokenReranker(BaseReranker):
    provider_name = "broken"

    def rerank(self, query, documents, top_k=None):
        return super().rerank(query, documents, top_k)


class BrokenVector(BaseVectorRepository):
    provider_name = "broken"

    def upsert(self, items):
        return super().upsert(items)

    def search(self, vector, top_k=10):
        return super().search(vector, top_k)


class BrokenGraph(BaseGraphRepository):
    provider_name = "broken"

    def upsert_graph_hints(self, hints):
        return super().upsert_graph_hints(hints)


class BrokenCache(BaseCacheRepository):
    provider_name = "broken"

    def get(self, key):
        return super().get(key)

    def set(self, key, value, ttl_seconds=None):
        return super().set(key, value, ttl_seconds)


class BrokenObjectStore(BaseObjectRepository):
    provider_name = "broken"

    def put_bytes(self, key, data, content_type=None):
        return super().put_bytes(key, data, content_type)

    def get_bytes(self, key):
        return super().get_bytes(key)


class BrokenDatabase(BaseDatabaseRepository):
    provider_name = "broken"

    def execute(self, statement, parameters=None):
        return super().execute(statement, parameters)


def test_base_methods_raise_not_implemented():
    with pytest.raises(NotImplementedError):
        list(BrokenConnector().discover())
    with pytest.raises(NotImplementedError):
        BrokenConnector().load(SourceRecord("x", "kind", "locator"))
    with pytest.raises(NotImplementedError):
        BrokenParser().parse(RawDocument("x", "src", "text", "text/plain"))
    with pytest.raises(NotImplementedError):
        BrokenChat().respond("hi")
    with pytest.raises(NotImplementedError):
        BrokenEmbedding().embed(["hi"])
    with pytest.raises(NotImplementedError):
        BrokenReranker().rerank("q", ["d"])
    with pytest.raises(NotImplementedError):
        BrokenVector().upsert([])
    with pytest.raises(NotImplementedError):
        BrokenVector().search([1.0])
    with pytest.raises(NotImplementedError):
        BrokenGraph().upsert_graph_hints([])
    with pytest.raises(NotImplementedError):
        BrokenCache().get("k")
    with pytest.raises(NotImplementedError):
        BrokenCache().set("k", "v")
    with pytest.raises(NotImplementedError):
        BrokenObjectStore().put_bytes("k", b"v")
    with pytest.raises(NotImplementedError):
        BrokenObjectStore().get_bytes("k")
    with pytest.raises(NotImplementedError):
        BrokenDatabase().execute("select 1")


def test_adapter_registry_and_builder_all_families():
    registry = AdapterRegistry()
    registry.register_connector("connector", MockConnector)
    registry.register_parser("parser", MockMarkdownParser)
    registry.register_model("chat", MockChatModel)
    registry.register_repository("vector", MockVectorRepository)
    builder = AdapterBuilder(registry)
    assert builder.build_connector("connector").provider_name == "mock"
    assert builder.build_parser("parser").parser_name == "mock_markdown"
    assert builder.build_model("chat").respond("hello").text == "Echo: hello"
    assert builder.build_repository("vector").provider_name == "mock_vector"
    for getter, kind in [
        (registry.get_connector, "missing"),
        (registry.get_parser, "missing"),
        (registry.get_model, "missing"),
        (registry.get_repository, "missing"),
    ]:
        with pytest.raises(ValueError):
            getter(kind)


def test_mock_connectors_parser_models_and_repositories(tmp_path: Path):
    local = tmp_path / "doc.md"
    local.write_text("# Title\n\nBody", encoding="utf-8")
    raw = MockConnector(text="# Harbor\n\nBody").load(next(MockConnector().discover()))
    assert raw.metadata["title"] == "Mock Document"
    local_connector = MockLocalTextFileConnector(tmp_path)
    local_record = next(local_connector.discover())
    assert local_connector.load(local_record).text().startswith("# Title")
    parsed = MockMarkdownParser().parse(raw)
    assert [element.type for element in parsed.elements] == ["heading", "paragraph"]
    assert MockChatModel().respond("world").text == "Echo: world"
    embeddings = MockEmbeddingModel().embed(["aa", "bbb"]).vectors
    assert len(embeddings) == 2 and len(embeddings[0]) == 8
    ranked = MockReranker().rerank("harbor rag", ["harbor", "nothing"], top_k=1)
    assert ranked[0].index == 0
    vector = MockVectorRepository()
    vector.upsert(
        [
            {"id": "a", "text": "A", "vector": [1.0, 0.0], "metadata": {"m": "x"}},
            {"id": "b", "text": "B", "vector": [0.0, 1.0]},
        ]
    )
    assert vector.search([1.0, 0.0], top_k=1)[0].id == "a"
    graph = MockGraphRepository()
    graph.upsert_graph_hints([GraphHint("a", "rel", "b", "Doc", "Doc")])
    assert graph.edges[0]["relation"] == "rel"
    cache = MockCacheRepository()
    cache.set("k", "v")
    assert cache.get("k") == "v"
    obj = MockObjectRepository()
    assert obj.put_bytes("k", b"data") == "memory://k"
    assert obj.get_bytes("k") == b"data"
    db = MockDatabaseRepository()
    assert db.execute("select 1", [1]) == []
    assert db.statements == [("select 1", (1,))]
