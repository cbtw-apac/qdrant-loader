from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True, slots=True)
class HarborId:
    value: str

    def __post_init__(self) -> None:
        if not self.value.startswith("harbor://"):
            raise ValueError("HarborId must start with 'harbor://'.")
        if any(ch.isspace() for ch in self.value):
            raise ValueError("HarborId must not contain whitespace.")

    def __str__(self) -> str:
        return self.value


def stable_hash_id(namespace: str, *parts: object) -> HarborId:
    raw = "|".join(str(p) for p in parts)
    digest = sha256(raw.encode("utf-8")).hexdigest()[:24]
    return HarborId(f"harbor://{namespace.strip('/')}/{digest}")
