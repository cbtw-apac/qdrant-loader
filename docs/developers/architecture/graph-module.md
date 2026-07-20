# Graph Module Documentation

## 📋 Overview

The **Graph Module** is a core component of QDrant Loader that enables extraction, storage, and traversal of knowledge graphs from various data sources. It provides a backend-agnostic interface for building entity-relationship graphs from documents, allowing developers to:

- Extract structured entities (documents, people, containers, concepts) from unstructured data
- Create relationships between entities (authored_by, belongs_to, has_label, etc.)
- Store graphs in graph databases like FalkorDB or Neptune
- Query and traverse graph relationships for enhanced semantic search

### Key Benefits

- **Backend-Agnostic Design**: Pluggable graph store implementations (FalkorDB, Neptune, etc.)
- **Source-Specific Extractors**: Built-in extractors for Jira, Confluence, Git, and local files
- **Batch Operations**: Efficient bulk insert/update operations for high-throughput ingestion
- **Project Isolation**: Multi-project support with automatic project-scoped queries
- **Async-First**: Non-blocking I/O for scalable graph operations

### Use Cases

- **Enterprise Knowledge Graphs**: Build comprehensive entity networks from Jira, Confluence, and Git repositories
- **Entity Linking**: Connect documents, people, and topics across multiple data sources
- **Semantic Search Enhancement**: Use graph relationships to expand and contextualize search queries
- **Relationship Discovery**: Find connections between entities that would be hidden in linear document search

## 🏗️ Architecture

### Component Hierarchy

```
┌─────────────────────────────────────────────────────────────┐
│ Graph Module (qdrant_loader_core.graph)                      │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────────────┐        ┌──────────────────────┐   │
│  │   Graph Interface    │        │  Entity Extractors   │   │
│  ├──────────────────────┤        ├──────────────────────┤   │
│  │ - GraphStore (ABC)   │        │ - EntityExtractor    │   │
│  │ - Models             │        │ - BaseEntityExtractor│   │
│  │ - FalkorGraphStore   │        │ - JiraEntityExtractor│   │
│  │                      │        │ - ConfluenceExtractor│   │
│  └──────────────────────┘        │ - GitEntityExtractor │   │
│                                  │ - LocalFileExtractor │   │
│                                  │ - PublicDocsExtractor│   │
│                                  └──────────────────────┘   │
│                                                               │
│  ┌──────────────────────┐        ┌──────────────────────┐   │
│  │   Data Models        │        │  Schema Utilities    │   │
│  ├──────────────────────┤        ├──────────────────────┤   │
│  │ - GraphNode          │        │ - Schema initialization
│  │ - GraphEdge          │        │ - Node label enums   │   │
│  │ - SubGraph           │        │ - Edge type enums    │   │
│  │ - PersonInfo         │        │                      │   │
│  └──────────────────────┘        └──────────────────────┘   │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

### Data Model

#### GraphNode

Represents an entity in the graph with a unique identity and properties.

```python
@dataclass
class GraphNode:
    id: str                           # Unique node identifier
    label: str                        # Node type (Document, Person, etc.)
    project: str | None = None        # Project namespace (multi-project support)
    properties: dict[str, Any] = {}   # Custom properties (content, metadata, etc.)
```

**Supported Node Labels** (CoreNodeLabel):

- `DOCUMENT` - Represents a document/content item
- `PERSON` - Represents a user or author
- `CONTAINER` - Project/space/repository (logical grouping)
- `LABEL` - Tags or categories
- `CONCEPT` - Abstract concepts or entities
- `CHUNK` - Text segments or paragraphs
- `URL` - External URL references
- `ATTACHMENT` - File attachments

#### GraphEdge

Represents a directed relationship between two nodes.

```python
@dataclass
class GraphEdge:
    source: str                       # Source node ID
    target: str                       # Target node ID
    edge_type: str                    # Relationship type
    project: str | None = None        # Project namespace
    properties: dict[str, Any] = {}   # Relationship metadata (role, kind, etc.)
```

**Supported Edge Types** (CoreEdgeType):

- `AUTHORED_BY` - Person created/wrote the document (properties: `role`)
- `BELONGS_TO` - Document belongs to a container/project
- `HAS_LABEL` - Document has a label/tag
- `LINKS_TO` - Document links to external URL
- `PART_OF` - Hierarchical containment (section → document)
- `HAS_CHUNK` - Document contains a text chunk
- `HAS_CHILD` - Parent-child relationships
- `HAS_ATTACHMENT` - Document has attached files

#### SubGraph

A collection of nodes and edges forming a connected component.

```python
@dataclass
class SubGraph:
    nodes: list[GraphNode] = []       # Graph nodes
    edges: list[GraphEdge] = []       # Graph edges
```

#### PersonInfo

Represents author/contributor metadata.

```python
@dataclass
class PersonInfo:
    id: str                           # Unique person identifier
    display_name: str                 # Full display name
    email: str | None = None          # Email address
    username: str | None = None       # Username/handle
    source_type: str | None = None    # Source system (jira, confluence, etc.)
    source_id: str | None = None      # Source-specific ID
```

## 🔌 Core Components

### GraphStore Interface

Abstract interface defining the graph storage contract. All graph backends must implement this interface.

**Key Methods:**

```python
class GraphStore(ABC):
    # Node operations
    async def upsert_node(node: GraphNode) -> None
    async def upsert_nodes_batch(nodes: list[GraphNode]) -> None

    # Edge operations
    async def upsert_edge(edge: GraphEdge) -> None
    async def upsert_edges_batch(edges: list[GraphEdge]) -> None

    # Query operations
    async def neighbors(
        node_id: str,
        depth: int,
        edge_types: list[str] | None = None,
        project: str | None = None,
    ) -> SubGraph

    async def query_cypher(
        cypher: str,
        params: dict[str, Any],
    ) -> list[list[Any]]
```

**Implementation:**

- **FalkorGraphStore** - FalkorDB implementation (Redis-based graph database)
  - Uses Cypher query language
  - Supports connection pooling and async operations
  - Multi-project isolation via project field

### EntityExtractor Interface

Abstract interface for source-specific entity extraction. Each data source has a dedicated extractor.

**Key Methods:**

```python
class EntityExtractor(ABC):
    async def extract(doc: Document) -> SubGraph

    @classmethod
    def register_extractor(source_type: str, extractor_cls: type)

    @classmethod
    def for_source(source_type: str) -> EntityExtractor
```

**Built-in Extractors:**

| Extractor                   | Source      | Extracts                                           |
| --------------------------- | ----------- | -------------------------------------------------- |
| `JiraEntityExtractor`       | Jira        | Issues, assignees, reporters, projects, components |
| `ConfluenceEntityExtractor` | Confluence  | Pages, authors, spaces, child pages                |
| `GitEntityExtractor`        | Git         | Commits, authors, files, repositories              |
| `LocalFileEntityExtractor`  | Local files | Files, folders, metadata                           |
| `PublicDocsEntityExtractor` | Public docs | Pages, links, metadata                             |

### FalkorGraphStore

Concrete implementation using FalkorDB (Redis-based graph database).

**Features:**

- Connection pooling with configurable max connections
- Batch insert optimization (groups by label/type)
- Project-based multi-tenancy
- Cypher query support
- Automatic node/edge validation

**Configuration:**

```python
store = FalkorGraphStore(
    host="localhost",           # FalkorDB host
    port=6379,                  # FalkorDB port
    password=None,              # Optional password
    graph_name="default_graph", # Graph name
    max_connections=10          # Connection pool size
)
```

## 📖 API Reference

### Core Methods

#### Upserting Nodes

```python
# Single node
node = GraphNode(
    id="doc-123",
    label="Document",
    project="project-a",
    properties={
        "title": "Quarterly Report",
        "created_at": "2026-01-15",
        "author_count": 3
    }
)
await store.upsert_node(node)

# Batch insert
nodes = [
    GraphNode(id="doc-1", label="Document", project="proj-a"),
    GraphNode(id="doc-2", label="Document", project="proj-a"),
    GraphNode(id="person-1", label="Person", project="proj-a"),
]
await store.upsert_nodes_batch(nodes)
```

#### Upserting Edges

```python
# Single edge
edge = GraphEdge(
    source="doc-123",
    target="person-1",
    edge_type="AUTHORED_BY",
    project="project-a",
    properties={"role": "author"}
)
await store.upsert_edge(edge)

# Batch insert
edges = [
    GraphEdge(source="doc-1", target="person-1", edge_type="AUTHORED_BY"),
    GraphEdge(source="doc-1", target="proj-a", edge_type="BELONGS_TO"),
]
await store.upsert_edges_batch(edges)
```

#### Traversing the Graph

```python
# Get all neighbors up to depth 2
subgraph = await store.neighbors(
    node_id="doc-123",
    depth=2,
    project="project-a"
)

# Get only specific relationship types
subgraph = await store.neighbors(
    node_id="person-1",
    depth=1,
    edge_types=["AUTHORED_BY", "BELONGS_TO"],
    project="project-a"
)

# Process results
for node in subgraph.nodes:
    print(f"Node: {node.id} ({node.label})")
for edge in subgraph.edges:
    print(f"Edge: {edge.source} -[{edge.edge_type}]-> {edge.target}")
```

#### Custom Cypher Queries

```python
# Execute raw Cypher for advanced patterns
result = await store.query_cypher(
    cypher="""
    MATCH (doc:Document)-[r:AUTHORED_BY]->(person:Person)
    WHERE doc.project = $project
    RETURN doc.id, person.display_name, r.role
    """,
    params={"project": "project-a"}
)

for row in result:
    doc_id, author_name, role = row
    print(f"{doc_id} written by {author_name} as {role}")
```

## 🔧 Configuration

### Environment Variables

| Variable                | Type   | Default         | Description                  |
| ----------------------- | ------ | --------------- | ---------------------------- |
| `GRAPH_HOST`            | string | `localhost`     | FalkorDB host address        |
| `GRAPH_PORT`            | int    | `6379`          | FalkorDB port number         |
| `GRAPH_PASSWORD`        | string | -               | FalkorDB password (optional) |
| `GRAPH_NAME`            | string | `default_graph` | Graph database name          |
| `GRAPH_MAX_CONNECTIONS` | int    | `10`            | Connection pool size         |

### Configuration File (config.yaml)

```yaml
global:
  graph:
    enabled: true # Enable graph extraction
    backend: falkordb # Graph store backend
    host: "localhost" # FalkorDB host
    port: 6379 # FalkorDB port
    password: null # FalkorDB password
    graph_name: "default_graph" # Graph name
    max_connections: 10 # Connection pool size
    extraction:
      enabled: true # Enable automatic extraction
      sources:
        - jira
        - confluence
        - git
        - localfile
```

### FalkorDB Setup

```bash
# Start FalkorDB via Docker
docker run -d -p 6379:6379 falkordb/falkordb:latest
```

## 🚀 Usage Examples

```python
# Initialize and extract from Jira
store = await get_graph_store(host="localhost", port=6379)
extractor = EntityExtractor.for_source("jira")
subgraph = await extractor.extract(doc)

# Store extracted entities
await store.upsert_nodes_batch(subgraph.nodes)
await store.upsert_edges_batch(subgraph.edges)

# Query the graph
result = await store.neighbors(
    node_id="jira-PROJ-123",
    depth=2,
    project="my-project"
)
```

## 🔌 Extending the Graph Module

### Custom Entity Extractor

Extend `BaseEntityExtractor` and implement the `extract()` method to support new data sources:

```python
from qdrant_loader_core.graph.extractor.base_extractor import BaseEntityExtractor

class CustomExtractor(BaseEntityExtractor):
    source_type = "custom"
    async def extract(self, doc: Document) -> SubGraph:
        # Build nodes and edges from doc
        return SubGraph(nodes=[...], edges=[...])

EntityExtractor.register_extractor("custom", CustomExtractor)
```

### Custom Graph Backend

Implement the `GraphStore` interface for new database backends:

```python
from qdrant_loader_core.graph.base import GraphStore

class CustomGraphStore(GraphStore):
    async def upsert_node(self, node: GraphNode) -> None: ...
    async def upsert_nodes_batch(self, nodes: list[GraphNode]) -> None: ...
    async def upsert_edge(self, edge: GraphEdge) -> None: ...
    async def upsert_edges_batch(self, edges: list[GraphEdge]) -> None: ...
    async def neighbors(self, node_id: str, depth: int, ...) -> SubGraph: ...
    async def query_cypher(self, cypher: str, params: dict) -> list[list[Any]]: ...
```

## ⚙️ Best Practices

1. **Batch Operations** - Use batch methods for better performance than individual inserts
2. **Project Isolation** - Always specify `project` parameter for multi-project queries
3. **Node ID Uniqueness** - Use prefixed IDs like `source:source_id` (e.g., `jira:PROJ-123`)
4. **Error Handling** - Only use labels from `CoreNodeLabel` enum for node validation
5. **Connection Management** - Initialize graph store once and reuse across operations

## 🧪 Testing

Tests are in `packages/qdrant-loader-core/tests/`:

- `test_graph_base.py`, `test_falkor_store.py`, `test_graph_init.py`
- `test_*_extractor.py` - source-specific extractors

```bash
cd packages/qdrant-loader-core
pytest tests/test_graph*.py -v
```

## 🔍 Troubleshooting

**Connection Errors**: Verify FalkorDB is running with `redis-cli ping`. Check host/port in configuration.

**Invalid Node Label**: Only use labels from `CoreNodeLabel` enum (DOCUMENT, PERSON, CONTAINER, LABEL, CONCEPT, CHUNK, URL, ATTACHMENT).

**Project Scope Issues**: Always pass `project` parameter to `neighbors()` queries for correct scoping.

**Memory Issues**: Reduce batch size or process data in smaller chunks during bulk imports.

## 📚 Related Documentation

- [Architecture Overview](README.md) - System-wide architecture
- [Entity Extraction Guide](../extending/README.md) - Extending entity extractors
- [Cross-Document Intelligence](../users/detailed-guides/mcp-server.md) - Using graphs in search
- [Configuration Reference](../users/configuration/README.md) - All configuration options

## 🤝 Contributing

To contribute graph-related improvements:

1. Add new extractors in `packages/qdrant-loader-core/src/qdrant_loader_core/graph/extractor/`
2. Register extractors in `packages/qdrant-loader-core/src/qdrant_loader_core/graph/registry.py`
3. Add comprehensive unit tests in `packages/qdrant-loader-core/tests/`
4. Update this documentation with new patterns and examples

## 📖 API Versioning

Current API Version: **1.0**

The Graph Module API is stable and production-ready. Breaking changes will be announced in the CHANGELOG with migration guides.

---

Last Updated: 2026-07-20  
Maintainer: Qdrant Loader Team
