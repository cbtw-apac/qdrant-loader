from __future__ import annotations

from abc import ABC, abstractmethod

from harborrag_core.ports.models import ChatResponse


class BaseChatModel(ABC):
    """Base class for chat/generation adapters.

    TODO: Implement provider adapters by translating Harbor messages into provider-native
    request payloads, redacting secrets from diagnostics, and returning ChatResponse without
    leaking raw provider output unless diagnostic mode is explicitly enabled.
    """

    provider_name: str

    @abstractmethod
    def respond(self, messages: str) -> ChatResponse:
        raise NotImplementedError
