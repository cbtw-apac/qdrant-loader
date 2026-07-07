from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CapabilityProfile:
    sync: bool = True
    async_: bool = False
    streaming: bool = False
    batch: bool = False
    permissions: bool = False
    metadata: bool = True

    def require(self, capability: str) -> None:
        if not hasattr(self, capability):
            raise ValueError(f"Unknown capability: {capability}")
        if not bool(getattr(self, capability)):
            raise NotImplementedError(f"Capability not supported: {capability}")
