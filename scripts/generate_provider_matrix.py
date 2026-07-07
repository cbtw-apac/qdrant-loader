"""Print the provider/repository implementation matrix.

Scans the adapter families under harborrag_adapters for implemented provider
modules (anything besides base/mock scaffolding) and collects TODO(...)
comments across all packages so contributors can see what to build next.

Usage:
    python scripts/generate_provider_matrix.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ADAPTERS_SRC = (
    REPO_ROOT / "packages" / "harborrag-adapters" / "src" / "harborrag_adapters"
)
PACKAGES_DIR = REPO_ROOT / "packages"

FAMILIES = [
    "connectors",
    "parsers",
    "models/chat",
    "models/embedding",
    "models/reranker",
    "repositories/vector",
    "repositories/graph",
    "repositories/cache",
    "repositories/object_store",
    "repositories/database",
]

SCAFFOLDING = {"__init__.py", "base.py", "mock.py", "__pycache__"}

TODO_PATTERN = re.compile(r"#\s*TODO\(([^)]+)\):\s*(.+)")


def list_providers(family: str) -> list[str]:
    family_dir = ADAPTERS_SRC / family
    if not family_dir.is_dir():
        return []
    providers = []
    for entry in sorted(family_dir.iterdir()):
        if entry.name in SCAFFOLDING:
            continue
        if entry.is_dir() or entry.suffix == ".py":
            providers.append(entry.stem if entry.is_file() else entry.name)
    return providers


def collect_todos() -> list[tuple[str, str, int, str]]:
    todos: list[tuple[str, str, int, str]] = []
    for path in sorted(PACKAGES_DIR.glob("*/src/**/*.py")):
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            match = TODO_PATTERN.search(line)
            if match:
                relative = str(path.relative_to(REPO_ROOT))
                todos.append(
                    (match.group(1), relative, line_number, match.group(2).strip())
                )
    return todos


def main() -> int:
    print("Provider/repository matrix (mock scaffolding excluded):")
    width = max(len(family) for family in FAMILIES)
    for family in FAMILIES:
        providers = list_providers(family)
        status = ", ".join(providers) if providers else "TODO: no real provider yet"
        print(f"  {family.ljust(width)}  {status}")

    todos = collect_todos()
    print()
    if todos:
        print(f"Open TODO items ({len(todos)}):")
        for scope, path, line_number, text in todos:
            print(f"  [{scope}] {path}:{line_number}: {text}")
    else:
        print("No TODO(...) items found in package sources.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
