# Testing

Every package owns its own test folder — there is no shared/global test suite that mixes packages:

```text
tests/                              cross-package + website build tests
packages/harborrag-core/tests/
packages/harborrag-adapters/tests/
packages/harborrag-engine/tests/
packages/harborrag-runtime/tests/
packages/harborrag-app/tests/
packages/harborrag-mcp/tests/
packages/harborrag/tests/
```

Add tests next to the package you modify. The root `tests/` folder is reserved for checks that span packages (currently the website build test suite) or repository-wide architecture rules.

## Running tests

```bash
pytest                                        # everything
pytest --cov --cov-report=term-missing        # with coverage
make test-package PACKAGE=harborrag-core      # a single package
```

`make test` runs the same as plain `pytest`; both are driven by `[tool.pytest.ini_options]` in the workspace `pyproject.toml`, which lists every package's `tests/` directory under `testpaths`.

## Coverage gate

```bash
make coverage
```

`[tool.coverage.report].fail_under = 95` in `pyproject.toml` — coverage below 95% fails the command (and CI's `quality-gates.yml`). `[tool.coverage.run].source` lists every package's `src/` directory, so coverage is measured on implementation code, not test code.

## Markers

Defined in `[tool.pytest.ini_options].markers`:

```text
slow          marks tests as slow (deselect with '-m not slow')
integration   marks tests that require Docker, cloud credentials, or live services
unit          marks unit tests
smoke         fast import and wiring tests
blackbox      public API behavior tests
whitebox      internal architecture and contract tests
requires_deps marks tests requiring optional dependencies
workflow      marks tests that validate GitHub Actions workflow files
```

Tests requiring Docker, cloud credentials, provider accounts, or live model APIs must be marked `@pytest.mark.integration` and must not run by default — default CI should never require external services.

## Testing the base + mock pattern

Because every provider family ships a `base.py` contract and a `mock.py` implementation (see [Architecture Overview](../architecture/README.md#the-base-mock-pattern)), package-local tests typically:

1. instantiate the mock (e.g. `MockConnector`, `MockEmbeddingModel`, `MockVectorRepository`);
2. exercise the contract method (`discover()`/`load()`, `embed()`, `upsert()`/`search()`, ...);
3. assert on the shape and values of the returned core domain object (`SourceRecord`, `RawDocument`, `EmbeddingResponse`, `RetrievalResult`, ...).

`harborrag-core`'s `testing/fakes.py` (`FakeConnector`, `FakeParser`) exists for tests in other packages that need connector/parser behavior without importing `harborrag-adapters`.

When you implement a real provider, add its tests using a fake client or fixture data — not live credentials — so the default suite stays hermetic. A provider test suite typically mirrors the mock test's shape, but constructs the real class with a fake/stub of the underlying SDK client.

## Quality gates as a whole

```bash
make lint          # ruff check .
make typecheck      # mypy packages
make compile        # python -m compileall packages scripts
make deps-check      # scripts/check_dependency_direction.py
make coverage
```

All five run in `.github/workflows/quality-gates.yml` on every push/PR to `main`. `.github/workflows/test.yml` additionally runs each package's test suite in its own matrix job, plus the website build tests.

## Related

- [Architecture Overview](../architecture/README.md) — the package boundaries these tests protect.
- [Extending HarborRAG](../extending/README.md) — how to test a real provider you're adding.
