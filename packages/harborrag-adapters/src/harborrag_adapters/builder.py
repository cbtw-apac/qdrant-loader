from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from harborrag_adapters.registry import AdapterRegistry


@dataclass(slots=True)
class AdapterBuilder:
    """Builder for adapters, including connectors, parsers, models, and repositories."""

    registry: AdapterRegistry

    def build_connector(self, provider: str, **kwargs: Any) -> Any:
        return self.registry.get_connector(provider)(**kwargs)

    def build_parser(self, provider: str, **kwargs: Any) -> Any:
        return self.registry.get_parser(provider)(**kwargs)

    def build_model(self, provider: str, **kwargs: Any) -> Any:
        return self.registry.get_model(provider)(**kwargs)

    def build_repository(self, provider: str, **kwargs: Any) -> Any:
        return self.registry.get_repository(provider)(**kwargs)
