from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from .base import GraphEdge, GraphNode, GraphStore, SubGraph
from .schema.utils import init_schema

if TYPE_CHECKING:
    from .falkor_store import FalkorGraphStore

try:
    from .falkor_store import FalkorGraphStore
except ImportError:
    FalkorGraphStore = None


__all__ = [
    "FalkorGraphStore",
    "GraphNode",
    "GraphEdge",
    "GraphStore",
    "SubGraph",
]


_graph_store: FalkorGraphStore | None = None
_graph_store_lock = asyncio.Lock()


async def get_graph_store(
    host: str | None = None,
    port: int | None = None,
    graph_name: str | None = None,
    max_connections: int | None = None,
) -> FalkorGraphStore:
    global _graph_store

    if FalkorGraphStore is None:
        raise ModuleNotFoundError(
            "FalkorGraphStore requires the 'graph' extra.\n"
            "Install it with:\n"
            "    pip install qdrant-loader-core[graph]"
        )

    if _graph_store is None:
        async with _graph_store_lock:
            if _graph_store is None:
                final_host = host or "localhost"
                final_port = port if port is not None else 6379
                final_graph = graph_name or "default_graph"
                final_max_conn = max_connections if max_connections is not None else 10

                _graph_store = FalkorGraphStore(
                    host=final_host,
                    port=int(final_port),
                    graph_name=final_graph,
                    max_connections=final_max_conn,
                )

                await init_schema(_graph_store)

    return _graph_store
