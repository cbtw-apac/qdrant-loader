from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AdapterRegistry:
    """Registry for adapters, including connectors, parsers, models, and repositories."""

    connectors: dict[str, type[Any]] = field(default_factory=dict)
    parsers: dict[str, type[Any]] = field(default_factory=dict)
    models: dict[str, type[Any]] = field(default_factory=dict)
    repositories: dict[str, type[Any]] = field(default_factory=dict)

    def register_connector(self, name: str, cls: type[Any]) -> None:
        self.connectors[name] = cls

    def register_parser(self, name: str, cls: type[Any]) -> None:
        self.parsers[name] = cls

    def register_model(self, name: str, cls: type[Any]) -> None:
        self.models[name] = cls

    def register_repository(self, name: str, cls: type[Any]) -> None:
        self.repositories[name] = cls

    def get_connector(self, name: str) -> type[Any]:
        return _get(self.connectors, "connector", name)

    def get_parser(self, name: str) -> type[Any]:
        return _get(self.parsers, "parser", name)

    def get_model(self, name: str) -> type[Any]:
        return _get(self.models, "model", name)

    def get_repository(self, name: str) -> type[Any]:
        return _get(self.repositories, "repository", name)


def _get(mapping: dict[str, type[Any]], kind: str, name: str) -> type[Any]:
    """Retrieve an adapter class from the registry, raising a ValueError if not found."""
    try:
        return mapping[name]
    except KeyError as exc:
        raise ValueError(f"Unknown {kind}: {name}") from exc
