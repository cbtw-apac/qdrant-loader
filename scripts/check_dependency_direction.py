"""Check that cross-package imports follow the HarborRAG layering rules.

Allowed direction (lower layers never import higher ones):

    harborrag_core      -> (stdlib only)
    harborrag_adapters  -> core
    harborrag_engine    -> core, adapters
    harborrag_runtime   -> core, adapters, engine
    harborrag_app       -> core, engine, runtime
    harborrag_mcp       -> core, engine, runtime
    harborrag           -> any harborrag package (public facade)

Usage:
    python scripts/check_dependency_direction.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

ALLOWED_IMPORTS: dict[str, set[str]] = {
    "harborrag_core": set(),
    "harborrag_adapters": {"harborrag_core"},
    "harborrag_engine": {"harborrag_core", "harborrag_adapters"},
    "harborrag_runtime": {"harborrag_core", "harborrag_adapters", "harborrag_engine"},
    "harborrag_app": {"harborrag_core", "harborrag_engine", "harborrag_runtime"},
    "harborrag_mcp": {"harborrag_core", "harborrag_engine", "harborrag_runtime"},
    "harborrag": {
        "harborrag_core",
        "harborrag_adapters",
        "harborrag_engine",
        "harborrag_runtime",
        "harborrag_app",
        "harborrag_mcp",
    },
}

MODULE_TO_PACKAGE_DIR = {
    "harborrag_core": "harborrag-core",
    "harborrag_adapters": "harborrag-adapters",
    "harborrag_engine": "harborrag-engine",
    "harborrag_runtime": "harborrag-runtime",
    "harborrag_app": "harborrag-app",
    "harborrag_mcp": "harborrag-mcp",
    "harborrag": "harborrag",
}

IMPORT_PATTERN = re.compile(
    r"^\s*(?:from|import)\s+(harborrag(?:_[a-z]+)?)\b", re.MULTILINE
)


def find_violations() -> list[str]:
    violations: list[str] = []
    for module, package_dir in MODULE_TO_PACKAGE_DIR.items():
        src_dir = REPO_ROOT / "packages" / package_dir / "src" / module
        if not src_dir.is_dir():
            violations.append(f"missing package source directory: {src_dir}")
            continue
        allowed = ALLOWED_IMPORTS[module] | {module}
        for path in sorted(src_dir.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for match in IMPORT_PATTERN.finditer(text):
                imported = match.group(1)
                if imported not in allowed:
                    line = text.count("\n", 0, match.start()) + 1
                    relative = path.relative_to(REPO_ROOT)
                    violations.append(
                        f"{relative}:{line}: {module} must not import {imported}"
                    )
    return violations


def main() -> int:
    violations = find_violations()
    if violations:
        print("Dependency direction violations found:")
        for violation in violations:
            print(f"  {violation}")
        return 1
    print(
        "Dependency direction OK: all cross-package imports follow the layering rules."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
