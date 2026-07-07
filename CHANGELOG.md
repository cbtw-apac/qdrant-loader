# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-07-07

### Added

- Initial HarborRAG framework foundation with a ports-and-adapters workspace layout.
- `harborrag-core`: contracts, domain models, ports, execution, observability, and security primitives.
- `harborrag-adapters`: base classes and mocks for connectors, parsers, model adapters, and repositories.
- `harborrag-engine`: ingestion and retrieval orchestration skeleton.
- `harborrag-runtime`: runtime composition, local job state, and scheduling skeleton.
- `harborrag-app`: CLI and API package boundary with mock services.
- `harborrag-mcp`: MCP facade with policy and audit boundaries and mock tools.
- `harborrag`: meta-package public facade.
- Package-local test suites, mock pipeline script, dependency-direction check, and provider matrix generator.
- Deployment scaffolding under `deploy/` (Docker, Compose, Qdrant, FalkorDB, Temporal, monitoring) and helper scripts under `scripts/deployment/` and `scripts/models/`.
