from __future__ import annotations

from abc import ABC, abstractmethod


class BaseCliCommand(ABC):
    """Base class for CLI commands.

    TODO: Implement commands with JSON output mode, non-zero exit codes on errors, and stable
    machine-readable envelopes for automation.
    """

    name: str

    @abstractmethod
    def run(self, *, as_json: bool = False) -> int:
        raise NotImplementedError
