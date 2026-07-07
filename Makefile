SHELL := /bin/bash
PYTHON ?= python
PYTEST ?= pytest
PACKAGE ?=

.PHONY: help bootstrap install-dev test test-package coverage coverage-html lint format typecheck compile doctor mock-pipeline deps-check provider-matrix clean

help:
	@echo "HarborRAG development targets"
	@echo ""
	@echo "Setup:"
	@echo "  make bootstrap        Install workspace in editable mode with dev tools"
	@echo "  make install-dev      Alias for bootstrap"
	@echo ""
	@echo "Quality:"
	@echo "  make test             Run all root and package-local tests"
	@echo "  make test-package PACKAGE=harborrag-core"
	@echo "  make coverage         Run tests with 95% coverage gate"
	@echo "  make lint             Run Ruff lint checks"
	@echo "  make format           Format with Black, isort, then Ruff format"
	@echo "  make typecheck        Run mypy across packages"
	@echo "  make compile          Compile package and script Python files"
	@echo ""
	@echo "Diagnostics:"
	@echo "  make doctor           Run CLI doctor as JSON"
	@echo "  make mock-pipeline    Run deterministic mock pipeline"
	@echo "  make deps-check       Check package dependency direction"
	@echo "  make provider-matrix  Print provider/repository TODO matrix"
	@echo "  make clean            Remove Python build/test caches"

bootstrap:
	$(PYTHON) -m pip install -e packages/harborrag-core
	$(PYTHON) -m pip install -e packages/harborrag-adapters
	$(PYTHON) -m pip install -e packages/harborrag-engine
	$(PYTHON) -m pip install -e packages/harborrag-runtime
	$(PYTHON) -m pip install -e packages/harborrag-app
	$(PYTHON) -m pip install -e packages/harborrag-mcp
	$(PYTHON) -m pip install -e packages/harborrag
	$(PYTHON) -m pip install -e ".[dev]"

install-dev: bootstrap

test:
	$(PYTEST)

test-package:
	@if [[ -z "$(PACKAGE)" ]]; then \
		echo "Usage: make test-package PACKAGE=harborrag-core"; \
		exit 2; \
	fi
	$(PYTEST) packages/$(PACKAGE)/tests

coverage:
	$(PYTEST) --cov --cov-report=term-missing

coverage-html:
	$(PYTEST) --cov --cov-report=term-missing --cov-report=html

lint:
	ruff check .

format:
	black packages tests scripts
	isort packages tests scripts
	ruff format packages tests scripts

typecheck:
	mypy packages

compile:
	$(PYTHON) -m compileall -q packages scripts

doctor:
	$(PYTHON) -m harborrag_app.cli.main doctor --json

mock-pipeline:
	$(PYTHON) scripts/run_mock_pipeline.py --json

deps-check:
	$(PYTHON) scripts/check_dependency_direction.py

provider-matrix:
	$(PYTHON) scripts/generate_provider_matrix.py

clean:
	find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache -o -name .mypy_cache -o -name htmlcov \) -prune -exec rm -rf {} +
	find . -type f \( -name "*.pyc" -o -name ".coverage" -o -name "coverage.xml" \) -delete
