from __future__ import annotations

import asyncio
import datetime
import json
from collections import defaultdict
from enum import Enum
from typing import Any

from falkordb import FalkorDB

from .models import (
    CoreEdgeType,
    CoreNodeLabel,
    GraphEdge,
    GraphNode,
    SubGraph,
)
from .base import GraphStore

MAX_ROWS = 5000


class FalkorGraphStore(GraphStore):
    def __init__(
        self,
        host="localhost",
        port=6379,
        password=None,
        graph_name="default_graph",
        max_connections: int = 10,
    ):

        if max_connections < 1:
            raise ValueError("max_connections must be >= 1")
        self._semaphore = asyncio.Semaphore(max_connections)
        self._db = FalkorDB(host=host, port=port, password=password)
        self._graph = self._db.select_graph(graph_name)

    def _validate_node(self, node: GraphNode):
        if node.label not in {e.value for e in CoreNodeLabel}:
            raise ValueError(f"Invalid node label: {node.label}")

    def _validate_edge(self, edge: GraphEdge):
        if edge.edge_type not in {e.value for e in CoreEdgeType}:
            raise ValueError(f"Invalid edge type: {edge.edge_type}")

    def _node_payload(self, node: GraphNode) -> dict[str, Any]:
        props = self._clean_props(node.properties or {})
        # Pop (not get): project is the MERGE identity key, resolved once here.
        # Leaving it in props would let `SET n += props` overwrite that identity
        # right after MERGE if node.project differs from the stale properties value.
        props_project = props.pop("project", None)
        return {
            "id": node.id,
            "project": node.project or props_project,
            "props": props,
        }

    async def upsert_node(self, node: GraphNode) -> None:
        self._validate_node(node)

        payload = self._node_payload(node)

        # Match by (id, project) only, not label: an edge upsert may have already
        # created a stub node for this id before its real label was known. Adding
        # the label via SET (instead of matching on it) lets this MERGE find and
        # enrich that stub rather than creating a duplicate node.
        if payload["project"] is not None:
            query = f"""
            MERGE (n {{id: $id, project: $project}})
            SET n:{node.label}
            SET n += $props
            """
        else:
            query = f"""
            MERGE (n {{id: $id}})
            SET n:{node.label}
            SET n += $props
            """

        await self._run_query(query, payload)

    async def upsert_nodes_batch(self, nodes: list[GraphNode]) -> None:
        if not nodes:
            return
        for node in nodes:
            self._validate_node(node)
        grouped: dict[str, list[GraphNode]] = defaultdict(list)
        for node in nodes:
            grouped[node.label].append(node)

        tasks = []
        for label, group_nodes in grouped.items():
            payload = [self._node_payload(node) for node in group_nodes]
            with_project = [n for n in payload if n["project"] is not None]
            without_project = [n for n in payload if n["project"] is None]

            if with_project:
                tasks.append(
                    self._run_query(
                        f"""
                        UNWIND $nodes AS node
                        MERGE (n {{id: node.id, project: node.project}})
                        SET n:{label}
                        SET n += node.props
                        """,
                        {"nodes": with_project},
                    )
                )

            if without_project:
                tasks.append(
                    self._run_query(
                        f"""
                        UNWIND $nodes AS node
                        MERGE (n {{id: node.id}})
                        SET n:{label}
                        SET n += node.props
                        """,
                        {"nodes": without_project},
                    )
                )

        if tasks:
            await asyncio.gather(*tasks)

    def _edge_payload(self, edge: GraphEdge) -> dict[str, Any]:
        props = self._clean_props(edge.properties or {})
        # Pop (not get): project is the MERGE identity key, resolved once here.
        # Leaving it in props would let `SET r += props` overwrite that identity
        # right after MERGE if edge.project differs from the stale properties value.
        props_project = props.pop("project", None)
        return {
            "source": edge.source,
            "target": edge.target,
            "project": edge.project or props_project,
            "props": props,
        }

    async def upsert_edge(self, edge: GraphEdge) -> None:
        self._validate_edge(edge)
        payload = self._edge_payload(edge)

        # MERGE (not MATCH) the endpoints: the target of an edge (e.g. a linked
        # Jira issue) may not have been ingested yet. MATCH would silently drop
        # the edge with zero rows and no error; MERGE creates an unlabeled stub
        # node instead, which upsert_node later enriches with its real label.
        rel_pattern = (
            f"r:{edge.edge_type} {{kind: $props.kind}}"
            if "kind" in payload["props"]
            else f"r:{edge.edge_type}"
        )
        if payload["project"] is not None:
            query = f"""
            MERGE (a {{id: $source, project: $project}})
            MERGE (b {{id: $target, project: $project}})
            MERGE (a)-[{rel_pattern}]->(b)
            SET r += $props
            SET r.project = $project
            """
        else:
            query = f"""
            MERGE (a {{id: $source}})
            MERGE (b {{id: $target}})
            MERGE (a)-[{rel_pattern}]->(b)
            SET r += $props
            """
        await self._run_query(query, payload)

    async def upsert_edges_batch(
        self,
        edges: list[GraphEdge],
    ) -> None:
        if not edges:
            return
        for edge in edges:
            self._validate_edge(edge)
        grouped: dict[str, list[GraphEdge]] = defaultdict(list)
        for edge in edges:
            grouped[edge.edge_type].append(edge)

        tasks = []
        for edge_type, group_edges in grouped.items():
            payload = [self._edge_payload(edge) for edge in group_edges]

            typed = [e for e in payload if "kind" in e["props"]]
            untyped = [e for e in payload if "kind" not in e["props"]]

            for group, rel_pattern in (
                (typed, f"r:{edge_type} {{kind: e.props.kind}}"),
                (untyped, f"r:{edge_type}"),
            ):
                if not group:
                    continue
                with_project = [e for e in group if e["project"] is not None]
                without_project = [e for e in group if e["project"] is None]

                if with_project:
                    tasks.append(
                        self._run_query(
                            f"""
                        UNWIND $edges AS e
                        MERGE (a {{id: e.source, project: e.project}})
                        MERGE (b {{id: e.target, project: e.project}})
                        MERGE (a)-[{rel_pattern}]->(b)
                        SET r += e.props
                        SET r.project = e.project
                        """,
                            {"edges": with_project},
                        )
                    )
                if without_project:
                    tasks.append(
                        self._run_query(
                            f"""
                        UNWIND $edges AS e
                        MERGE (a {{id: e.source}})
                        MERGE (b {{id: e.target}})
                        MERGE (a)-[{rel_pattern}]->(b)
                        SET r += e.props
                        """,
                            {"edges": without_project},
                        )
                    )
        if tasks:
            await asyncio.gather(*tasks)

    async def neighbors(
        self,
        node_id: str,
        depth: int,
        edge_types: list[str] | None = None,
        project: str | None = None,
    ) -> SubGraph:
        edge_filter = ""
        if edge_types:
            invalid = [
                e for e in edge_types if e not in {et.value for et in CoreEdgeType}
            ]
            if invalid:
                raise ValueError(f"Invalid edge types: {invalid}")
            edge_filter = ":" + "|".join(edge_types)
        params = {"id": node_id}
        if project:
            params["project"] = project
            query = f"""
            MATCH (n {{id: $id, project: $project}})-[r{edge_filter}*1..{depth}]-(m {{project: $project}})
            RETURN n, r, m
            LIMIT {MAX_ROWS}
            """
        else:
            query = f"""
            MATCH (n {{id: $id}})-[r{edge_filter}*1..{depth}]-(m)
            RETURN n, r, m
            LIMIT {MAX_ROWS}
            """
        result = await self._run_query(query, params)
        nodes_map: dict[str, GraphNode] = {}
        internal_node_id_map: dict[int, str] = {}
        edges: list[GraphEdge] = []

        def _extract_node(node_value):
            if hasattr(node_value, "properties"):
                node_id = node_value.properties.get("id")
                label = (
                    node_value.labels[0]
                    if getattr(node_value, "labels", None)
                    else "Unknown"
                )
                properties = node_value.properties or {}
            elif isinstance(node_value, dict):
                node_id = node_value.get("id")
                label = node_value.get("label", "Unknown")
                properties = node_value
            else:
                node_id = str(node_value)
                label = "Unknown"
                properties = {}
            return node_id, label, properties

        def _normalize_relationships(rels_value):
            if rels_value is None:
                return []
            if isinstance(rels_value, list):
                return rels_value
            return [rels_value]

        def _resolve_internal_node_id(node_value):
            if isinstance(node_value, int):
                return internal_node_id_map.get(node_value, str(node_value))
            return node_value

        def _extract_edge(rel):
            if hasattr(rel, "src_node") and hasattr(rel, "dest_node"):
                source = _resolve_internal_node_id(rel.src_node)
                target = _resolve_internal_node_id(rel.dest_node)
                edge_type = getattr(rel, "relation", getattr(rel, "edge_type", None))
                properties = rel.properties or {}
                return GraphEdge(
                    source=source,
                    target=target,
                    edge_type=edge_type,
                    properties=properties,
                )
            if isinstance(rel, dict):
                return GraphEdge(
                    source=rel.get("source"),
                    target=rel.get("target"),
                    edge_type=rel.get("edge_type"),
                    properties=rel.get("properties", {}),
                )
            raise ValueError("Unsupported relationship result type")

        for row in result.result_set:
            if len(row) != 3:
                continue
            n, rels, m = row
            n_id, n_label, n_props = _extract_node(n)
            if hasattr(n, "id") and isinstance(n.id, int):
                internal_node_id_map[n.id] = n_id
            if n_id not in nodes_map:
                nodes_map[n_id] = GraphNode(id=n_id, label=n_label, properties=n_props)

            m_id, m_label, m_props = _extract_node(m)
            if hasattr(m, "id") and isinstance(m.id, int):
                internal_node_id_map[m.id] = m_id
            if m_id not in nodes_map:
                nodes_map[m_id] = GraphNode(id=m_id, label=m_label, properties=m_props)

            for rel in _normalize_relationships(rels):
                try:
                    edge = _extract_edge(rel)
                except ValueError:
                    continue
                edges.append(edge)
        return SubGraph(
            nodes=list(nodes_map.values()),
            edges=edges,
        )

    async def query_cypher(
        self,
        cypher: str,
        params: dict[str, Any],
    ) -> list[list[Any]]:
        result = await self._run_query(cypher, params or {})
        return result.result_set

    def _clean_props(self, props: dict) -> dict:
        def _normalize_value(v: Any):
            if v is None:
                return None

            if isinstance(v, (str, int, float, bool)):
                return v

            if isinstance(v, (datetime.datetime, datetime.date)):
                return v.isoformat()

            if isinstance(v, Enum):
                return v.value

            if isinstance(v, list):
                cleaned = []
                for item in v:
                    val = _normalize_value(item)

                    if isinstance(val, (str, int, float, bool)):
                        cleaned.append(val)
                    else:
                        if val is not None:
                            cleaned.append(str(val))
                return cleaned

            if isinstance(v, dict):
                try:
                    return json.dumps(v, ensure_ascii=False)
                except Exception:
                    return str(v)
            try:
                return str(v)
            except Exception:
                return None

        clean = {}
        for k, v in props.items():
            val = _normalize_value(v)
            if val is None:
                continue
            clean[k] = val
        return clean

    async def _run_query(self, query, params):
        async with self._semaphore:
            return await asyncio.to_thread(self._graph.query, query, params)
