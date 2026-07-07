# harborrag-engine

Owns RAG orchestration using core contracts and adapter base classes.

## Folder ownership

```text
ingestion/base.py + ingestion/mock.py
retrieval/base.py + retrieval/mock.py
indexing/base.py + indexing/mock.py
graph/base.py + graph/mock.py
```

## Team deliverables

- Implement production ingestion pipeline using only connector/parser/model/repository interfaces.
- Implement chunkers that preserve headings, tables, code blocks, and page metadata.
- Implement retrieval pipeline with rewrite, vector search, graph expansion, fusion, reranking, and evidence building.


## Package tests

Tests for this package live in:

```text
packages/harborrag-engine/tests/
```

Run from the repository root:

```bash
pytest packages/harborrag-engine/tests
```

Keep new tests in this folder when adding or changing behavior owned by this package.
