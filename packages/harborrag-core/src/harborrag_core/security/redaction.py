from __future__ import annotations

import re

_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*([^\s,;]+)"),
    re.compile(r"(?i)(authorization:\s*bearer\s+)([^\s,;]+)"),
]


def redact_secrets(text: str, replacement: str = "<redacted>") -> str:
    result = text
    for pattern in _PATTERNS:
        result = pattern.sub(lambda m: f"{m.group(1)}={replacement}", result)
    return result
