import datetime
import json
from enum import Enum
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from qdrant_loader_core.graph.falkor_store import GLOBAL_PROJECT, FalkorGraphStore
from qdrant_loader_core.graph.models import GraphEdge, GraphNode


class FakeFalkorNode:
    def __init__(self, id, labels, properties):
        self.id = id
        self.labels = labels
        self.properties = properties


class FakeFalkorRel:
    def __init__(self, src_node, dest_node, relation, properties):
        self.src_node = src_node
        self.dest_node = dest_node
        self.relation = relation
        self.properties = properties


@pytest.fixture
def mock_falkordb():
    with patch("qdrant_loader_core.graph.falkor_store.FalkorDB") as mock_cls:
        mock_db = MagicMock()
        mock_graph = MagicMock()
        mock_db.select_graph.return_value = mock_graph
        mock_cls.return_value = mock_db
        yield mock_cls, mock_db, mock_graph


@pytest.fixture
def store(mock_falkordb):
    return FalkorGraphStore(host="localhost", port=6379, graph_name="test_graph")


def _fake_result(rows):
    result = MagicMock()
    result.result_set = rows
    return result


# ------------------------------------------------------------------
# __init__
# ------------------------------------------------------------------


def test_init_creates_db_and_selects_graph(mock_falkordb):
    mock_cls, mock_db, mock_graph = mock_falkordb

    store = FalkorGraphStore(
        host="h", port=1234, password="pw", graph_name="g", max_connections=5
    )

    mock_cls.assert_called_once_with(host="h", port=1234, password="pw")
    mock_db.select_graph.assert_called_once_with("g")
    assert store._graph is mock_graph
    assert store._semaphore._value == 5


def test_init_invalid_max_connections_raises(mock_falkordb):
    with pytest.raises(ValueError, match="max_connections must be >= 1"):
        FalkorGraphStore(max_connections=0)


# ------------------------------------------------------------------
# validation
# ------------------------------------------------------------------


def test_validate_node_valid_label_does_not_raise(store):
    store._validate_node(GraphNode(id="1", label="Document"))


def test_validate_node_invalid_label_raises(store):
    with pytest.raises(ValueError, match="Invalid node label"):
        store._validate_node(GraphNode(id="1", label="Bogus"))


def test_validate_edge_valid_type_does_not_raise(store):
    store._validate_edge(GraphEdge(source="1", target="2", edge_type="AUTHORED_BY"))


def test_validate_edge_invalid_type_raises(store):
    with pytest.raises(ValueError, match="Invalid edge type"):
        store._validate_edge(GraphEdge(source="1", target="2", edge_type="BOGUS"))


# ------------------------------------------------------------------
# _node_payload
# ------------------------------------------------------------------


def test_node_payload_uses_node_project(store):
    node = GraphNode(id="1", label="Document", project="proj", properties={"title": "t"})

    payload = store._node_payload(node)

    assert payload == {"id": "1", "project": "proj", "props": {"title": "t"}}


def test_node_payload_falls_back_to_props_project(store):
    node = GraphNode(
        id="1",
        label="Document",
        project=None,
        properties={"project": "from_props", "title": "t"},
    )

    payload = store._node_payload(node)

    assert payload["project"] == "from_props"
    assert "project" not in payload["props"]


def test_node_payload_defaults_to_global_project(store):
    node = GraphNode(id="1", label="Document", project=None, properties={})

    payload = store._node_payload(node)

    assert payload["project"] == GLOBAL_PROJECT


# ------------------------------------------------------------------
# upsert_node
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_node_with_project_builds_scoped_query(store):
    store._run_query = AsyncMock()
    node = GraphNode(id="1", label="Document", project="proj")

    await store.upsert_node(node)

    query, payload = store._run_query.await_args.args
    assert "project: $project" in query
    assert "SET n:Document" in query
    assert payload["project"] == "proj"


@pytest.mark.asyncio
async def test_upsert_node_invalid_label_raises(store):
    store._run_query = AsyncMock()

    with pytest.raises(ValueError):
        await store.upsert_node(GraphNode(id="1", label="Bad"))

    store._run_query.assert_not_awaited()


# ------------------------------------------------------------------
# upsert_nodes_batch
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_nodes_batch_empty_list_returns_immediately(store):
    store._run_query = AsyncMock()

    await store.upsert_nodes_batch([])

    store._run_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_upsert_nodes_batch_groups_by_label(store):
    store._run_query = AsyncMock()
    nodes = [
        GraphNode(id="1", label="Document", project="p1"),
        GraphNode(id="2", label="Person", project="p1"),
        GraphNode(id="3", label="Document", project="p1"),
    ]

    await store.upsert_nodes_batch(nodes)

    assert store._run_query.await_count == 2


@pytest.mark.asyncio
async def test_upsert_nodes_batch_invalid_label_raises(store):
    store._run_query = AsyncMock()

    with pytest.raises(ValueError):
        await store.upsert_nodes_batch([GraphNode(id="1", label="Bad")])

    store._run_query.assert_not_awaited()


# ------------------------------------------------------------------
# _edge_payload
# ------------------------------------------------------------------


def test_edge_payload_with_project_and_kind(store):
    edge = GraphEdge(
        source="a", target="b", edge_type="LINKS_TO", project="p", properties={"kind": "x"}
    )

    payload = store._edge_payload(edge)

    assert payload["project"] == "p"
    assert payload["props"]["kind"] == "x"


def test_edge_payload_falls_back_to_props_project(store):
    edge = GraphEdge(
        source="a",
        target="b",
        edge_type="LINKS_TO",
        project=None,
        properties={"project": "from_props"},
    )

    payload = store._edge_payload(edge)

    assert payload["project"] == "from_props"


def test_edge_payload_defaults_to_global_project(store):
    edge = GraphEdge(source="a", target="b", edge_type="LINKS_TO")

    payload = store._edge_payload(edge)

    assert payload["project"] == GLOBAL_PROJECT


# ------------------------------------------------------------------
# upsert_edge
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_edge_with_project_and_kind(store):
    store._run_query = AsyncMock()
    edge = GraphEdge(
        source="a", target="b", edge_type="LINKS_TO", project="p", properties={"kind": "related"}
    )

    await store.upsert_edge(edge)

    query, payload = store._run_query.await_args.args
    assert "kind: $props.kind" in query
    assert "project: $project" in query
    assert payload["project"] == "p"


@pytest.mark.asyncio
async def test_upsert_edge_without_explicit_project_defaults_to_global(store):
    store._run_query = AsyncMock()
    edge = GraphEdge(source="a", target="b", edge_type="LINKS_TO")

    await store.upsert_edge(edge)

    query, payload = store._run_query.await_args.args
    assert "project: $project" in query
    assert "kind: $props.kind" not in query
    assert payload["project"] == GLOBAL_PROJECT


@pytest.mark.asyncio
async def test_upsert_edge_invalid_type_raises(store):
    store._run_query = AsyncMock()

    with pytest.raises(ValueError):
        await store.upsert_edge(GraphEdge(source="a", target="b", edge_type="BOGUS"))

    store._run_query.assert_not_awaited()


# ------------------------------------------------------------------
# _edge_batch_query
# ------------------------------------------------------------------


def test_edge_batch_query_with_project(store):
    query = store._edge_batch_query("r:LINKS_TO", with_project=True)

    assert "project: e.project" in query
    assert "SET r.project = e.project" in query


def test_edge_batch_query_without_project(store):
    query = store._edge_batch_query("r:LINKS_TO", with_project=False)

    assert "SET r.project = e.project" not in query
    assert "e.project" not in query


# ------------------------------------------------------------------
# upsert_edges_batch
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_edges_batch_empty_list_returns_immediately(store):
    store._run_query = AsyncMock()

    await store.upsert_edges_batch([])

    store._run_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_upsert_edges_batch_groups_typed_and_untyped_with_and_without_project(store):
    store._run_query = AsyncMock()
    edges = [
        GraphEdge(
            source="a", target="b", edge_type="LINKS_TO", project="p", properties={"kind": "x"}
        ),
        GraphEdge(source="c", target="d", edge_type="LINKS_TO", properties={}),
    ]

    await store.upsert_edges_batch(edges)

    assert store._run_query.await_count == 2


@pytest.mark.asyncio
async def test_upsert_edges_batch_invalid_type_raises(store):
    store._run_query = AsyncMock()

    with pytest.raises(ValueError):
        await store.upsert_edges_batch([GraphEdge(source="a", target="b", edge_type="BOGUS")])

    store._run_query.assert_not_awaited()


# ------------------------------------------------------------------
# neighbors
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_neighbors_invalid_edge_type_raises(store):
    with pytest.raises(ValueError, match="Invalid edge types"):
        await store.neighbors(node_id="1", depth=1, edge_types=["BOGUS"])


@pytest.mark.asyncio
async def test_neighbors_with_project_and_edge_types_extracts_falkor_objects(store):
    n = FakeFalkorNode(id=1, labels=["Document"], properties={"id": "doc1"})
    m = FakeFalkorNode(id=2, labels=["Person"], properties={"id": "person1"})
    rel = FakeFalkorRel(src_node=1, dest_node=2, relation="AUTHORED_BY", properties={"role": "author"})
    store._run_query = AsyncMock(return_value=_fake_result([[n, rel, m]]))

    subgraph = await store.neighbors(
        node_id="doc1", depth=2, edge_types=["AUTHORED_BY"], project="proj"
    )

    query, params = store._run_query.await_args.args
    assert "project: $project" in query
    assert ":AUTHORED_BY" in query
    assert params == {"id": "doc1", "project": "proj"}

    assert {node.id for node in subgraph.nodes} == {"doc1", "person1"}
    assert len(subgraph.edges) == 1
    assert subgraph.edges[0].source == "doc1"
    assert subgraph.edges[0].target == "person1"
    assert subgraph.edges[0].edge_type == "AUTHORED_BY"


@pytest.mark.asyncio
async def test_neighbors_without_project_builds_unscoped_query(store):
    store._run_query = AsyncMock(return_value=_fake_result([]))

    subgraph = await store.neighbors(node_id="1", depth=1)

    query, params = store._run_query.await_args.args
    assert "$project" not in query
    assert params == {"id": "1"}
    assert subgraph.nodes == []
    assert subgraph.edges == []


@pytest.mark.asyncio
async def test_neighbors_extracts_dict_nodes_and_edges(store):
    n = {"id": "doc1", "label": "Document"}
    m = {"id": "person1", "label": "Person"}
    rel = {"source": "doc1", "target": "person1", "edge_type": "AUTHORED_BY", "properties": {}}
    store._run_query = AsyncMock(return_value=_fake_result([[n, [rel], m]]))

    subgraph = await store.neighbors(node_id="doc1", depth=1)

    assert len(subgraph.nodes) == 2
    assert subgraph.edges[0].source == "doc1"
    assert subgraph.edges[0].target == "person1"


@pytest.mark.asyncio
async def test_neighbors_extracts_fallback_scalar_nodes(store):
    store._run_query = AsyncMock(
        return_value=_fake_result([["raw_node_value", None, "raw_target_value"]])
    )

    subgraph = await store.neighbors(node_id="1", depth=1)

    assert {node.id for node in subgraph.nodes} == {"raw_node_value", "raw_target_value"}
    assert subgraph.edges == []


@pytest.mark.asyncio
async def test_neighbors_skips_malformed_rows(store):
    store._run_query = AsyncMock(return_value=_fake_result([[1, 2]]))

    subgraph = await store.neighbors(node_id="1", depth=1)

    assert subgraph.nodes == []
    assert subgraph.edges == []


@pytest.mark.asyncio
async def test_neighbors_skips_unsupported_relationship_type(store):
    n = {"id": "doc1"}
    m = {"id": "person1"}
    store._run_query = AsyncMock(return_value=_fake_result([[n, [123], m]]))

    subgraph = await store.neighbors(node_id="doc1", depth=1)

    assert len(subgraph.nodes) == 2
    assert subgraph.edges == []


# ------------------------------------------------------------------
# query_cypher
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_cypher_returns_result_set(store):
    store._run_query = AsyncMock(return_value=_fake_result([["a", 1]]))

    result = await store.query_cypher("MATCH (n) RETURN n", {"x": 1})

    assert result == [["a", 1]]
    store._run_query.assert_awaited_once_with("MATCH (n) RETURN n", {"x": 1})


@pytest.mark.asyncio
async def test_query_cypher_defaults_none_params_to_empty_dict(store):
    store._run_query = AsyncMock(return_value=_fake_result([]))

    await store.query_cypher("MATCH (n) RETURN n", None)

    store._run_query.assert_awaited_once_with("MATCH (n) RETURN n", {})


# ------------------------------------------------------------------
# _clean_props
# ------------------------------------------------------------------


def test_clean_props_passes_through_primitives(store):
    props = {"a": "str", "b": 1, "c": 1.5, "d": True}

    assert store._clean_props(props) == props


def test_clean_props_drops_none_values(store):
    assert store._clean_props({"a": None}) == {}


def test_clean_props_serializes_datetime_and_date(store):
    dt = datetime.datetime(2026, 1, 1, 12, 0, 0)
    d = datetime.date(2026, 1, 1)

    result = store._clean_props({"dt": dt, "d": d})

    assert result["dt"] == dt.isoformat()
    assert result["d"] == d.isoformat()


def test_clean_props_serializes_enum_to_value(store):
    class Color(Enum):
        RED = "red"

    assert store._clean_props({"c": Color.RED}) == {"c": "red"}


def test_clean_props_keeps_list_of_primitives(store):
    assert store._clean_props({"tags": ["a", 1, True]}) == {"tags": ["a", 1, True]}


def test_clean_props_list_drops_none_items(store):
    assert store._clean_props({"items": [None, "a"]}) == {"items": ["a"]}


def test_clean_props_list_json_encodes_nested_dict(store):
    result = store._clean_props({"items": [{"x": 1}]})

    assert result["items"] == [json.dumps({"x": 1}, ensure_ascii=False)]


def test_clean_props_list_stringifies_nested_object(store):
    class Foo:
        def __str__(self):
            return "foo_str"

    result = store._clean_props({"items": [Foo()]})

    assert result["items"] == ["foo_str"]


def test_clean_props_dict_value_json_encoded(store):
    result = store._clean_props({"meta": {"a": 1}})

    assert result["meta"] == json.dumps({"a": 1}, ensure_ascii=False)


def test_clean_props_dict_value_falls_back_to_str_on_json_failure(store):
    class Unserializable:
        def __repr__(self):
            return "<Unserializable>"

    value = {"x": Unserializable()}

    result = store._clean_props({"meta": value})

    assert result["meta"] == str(value)


def test_clean_props_object_falls_back_to_str(store):
    class Foo:
        def __str__(self):
            return "custom"

    assert store._clean_props({"obj": Foo()}) == {"obj": "custom"}


def test_clean_props_drops_value_when_str_raises(store):
    class Bad:
        def __str__(self):
            raise Exception("boom")

    assert store._clean_props({"obj": Bad()}) == {}


# ------------------------------------------------------------------
# _run_query
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_query_delegates_to_graph_query_in_thread(mock_falkordb):
    _, _, mock_graph = mock_falkordb
    mock_graph.query.return_value = "result"
    store = FalkorGraphStore()

    result = await store._run_query("MATCH (n) RETURN n", {"a": 1})

    assert result == "result"
    mock_graph.query.assert_called_once_with("MATCH (n) RETURN n", {"a": 1})
