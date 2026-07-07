from __future__ import annotations

from dataclasses import dataclass

from harborrag_core.ports.models import ChatResponse

from harborrag_adapters.models.chat.base import BaseChatModel


@dataclass(slots=True)
class MockChatModel(BaseChatModel):
    """Test-only mock chat model for framework tests."""

    provider_name: str = "mock_chat"

    def respond(self, messages: str) -> ChatResponse:
        return ChatResponse(text=f"Echo: {messages}")
