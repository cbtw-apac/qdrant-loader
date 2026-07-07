from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

from harborrag_core.contracts.errors import HarborSecurityError


@dataclass(slots=True)
class UrlPolicy:
    allowed_schemes: set[str] = field(default_factory=lambda: {"http", "https", "file"})
    denied_hosts: set[str] = field(default_factory=set)

    def validate(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in self.allowed_schemes:
            raise HarborSecurityError(f"URL scheme is not allowed: {parsed.scheme}")
        if parsed.hostname in self.denied_hosts:
            raise HarborSecurityError(f"URL host is denied: {parsed.hostname}")
