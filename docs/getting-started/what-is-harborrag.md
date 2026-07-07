# What is HarborRAG?

HarborRAG is a modular, provider-agnostic Retrieval-Augmented Generation (RAG) framework for engineering knowledge. It is built around a ports-and-adapters (hexagonal) architecture so that connectors, parsers, model providers, and storage repositories can be implemented and swapped independently, without leaking provider SDKs into orchestration or business logic.

## Status: framework foundation

HarborRAG is not yet a finished product. The repository currently provides:

- stable core contracts, domain models, and protocol ports (`harborrag-core`);
- base classes with deterministic mock implementations for every provider family (`harborrag-adapters`);
- ingestion and retrieval orchestration skeletons (`harborrag-engine`);
- runtime composition, local job state, and scheduling scaffolding (`harborrag-runtime`);
- a CLI/API package boundary with a mock application service (`harborrag-app`);
- an MCP tool facade with policy and audit boundaries, backed by mock tools (`harborrag-mcp`);
- a meta-package public facade (`harborrag`).

There are no real connectors, parsers, model providers, or vector/graph/cache/object/database repositories implemented yet — those are exactly the areas the framework is designed for teammates to fill in, following the base-class-plus-mock pattern described in [Extending HarborRAG](../developers/extending/README.md).

## Why a ports-and-adapters framework?

Engineering RAG systems accumulate risk when provider SDKs, orchestration logic, and API/CLI surfaces are tangled together:

- swapping a vector database or an embedding provider becomes a rewrite instead of a new adapter;
- tests require live credentials because there is no seam to mock;
- CLI, HTTP, and MCP tool code duplicate business rules instead of sharing one service layer;
- dependency direction erodes until every package imports every other package.

HarborRAG addresses this by giving every capability family (connectors, parsers, chat/embedding/reranker models, vector/graph/cache/object/database repositories) a `base.py` contract and a co-located `mock.py` implementation, and by enforcing a one-directional dependency graph between packages:

```text
harborrag-core      (no dependencies on other HarborRAG packages)
harborrag-adapters  -> core
harborrag-engine    -> core, adapters
harborrag-runtime   -> core, adapters, engine
harborrag-app       -> core, engine, runtime
harborrag-mcp       -> core, engine, runtime
harborrag           -> any package (public facade)
```

This direction is enforced automatically by `scripts/check_dependency_direction.py` and `make deps-check`.

## Where to go next

- [Quick Start](quick-start.md) — install the workspace and run the deterministic mock pipeline end to end.
- [Architecture Overview](../developers/architecture/README.md) — package map, dependency rules, and a tour of core contracts.
- [Extending HarborRAG](../developers/extending/README.md) — how to implement a real connector, parser, model, or repository.
