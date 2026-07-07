from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EngineConfig:
    tenant: str = "default"
    environment: str = "local"
