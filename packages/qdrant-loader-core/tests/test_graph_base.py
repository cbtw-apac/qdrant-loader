import pytest
from qdrant_loader_core.graph.base import GraphStore
from qdrant_loader_core.graph.models import GraphEdge, GraphNode


class SuperCallingGraphStore(GraphStore):
    """Concrete subclass that delegates to the abstract default bodies via super()."""

    async def upsert_node(self, node):
        return await super().upsert_node(node)

    async def upsert_edge(self, edge):
        return await super().upsert_edge(edge)

    async def upsert_nodes_batch(self, nodes):
        return await super().upsert_nodes_batch(nodes)

    async def upsert_edges_batch(self, edges):
        return await super().upsert_edges_batch(edges)

    async def neighbors(self, node_id, depth, edge_types=None, project=None):
        return await super().neighbors(
            node_id, depth, edge_types=edge_types, project=project
        )

    async def query_cypher(self, cypher, params):
        return await super().query_cypher(cypher, params)


def test_graph_store_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        GraphStore()


def test_graph_store_missing_method_cannot_be_instantiated():
    class IncompleteGraphStore(GraphStore):
        async def upsert_node(self, node):
            return None

    with pytest.raises(TypeError):
        IncompleteGraphStore()


@pytest.mark.asyncio
async def test_upsert_node_default_raises_not_implemented():
    store = SuperCallingGraphStore()
    with pytest.raises(NotImplementedError):
        await store.upsert_node(GraphNode(id="1", label="Test"))


@pytest.mark.asyncio
async def test_upsert_edge_default_raises_not_implemented():
    store = SuperCallingGraphStore()
    with pytest.raises(NotImplementedError):
        await store.upsert_edge(GraphEdge(source="1", target="2", edge_type="REL"))


@pytest.mark.asyncio
async def test_upsert_nodes_batch_default_raises_not_implemented():
    store = SuperCallingGraphStore()
    with pytest.raises(NotImplementedError):
        await store.upsert_nodes_batch([GraphNode(id="1", label="Test")])


@pytest.mark.asyncio
async def test_upsert_edges_batch_default_raises_not_implemented():
    store = SuperCallingGraphStore()
    with pytest.raises(NotImplementedError):
        await store.upsert_edges_batch(
            [GraphEdge(source="1", target="2", edge_type="REL")]
        )


@pytest.mark.asyncio
async def test_neighbors_default_raises_not_implemented():
    store = SuperCallingGraphStore()
    with pytest.raises(NotImplementedError):
        await store.neighbors("1", depth=2, edge_types=["REL"], project="test")


@pytest.mark.asyncio
async def test_query_cypher_default_raises_not_implemented():
    store = SuperCallingGraphStore()
    with pytest.raises(NotImplementedError):
        await store.query_cypher("MATCH (n) RETURN n", {})
