from dataclasses import dataclass

from harborrag_engine.config import EngineConfig
from harborrag_engine.policy import EnginePolicy


@dataclass(slots=True)
class EngineBuilder:
    config: EngineConfig = EngineConfig()
    policy: EnginePolicy = EnginePolicy()

    def diagnostics(self) -> dict[str, str | int]:
        return {
            "tenant": self.config.tenant,
            "environment": self.config.environment,
            "max_concurrency": self.policy.max_concurrency,
        }
