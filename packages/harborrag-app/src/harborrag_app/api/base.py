from __future__ import annotations

from abc import ABC, abstractmethod


class BaseApiController(ABC):
    """Base class for API route controllers.

    TODO: Implement FastAPI controllers with typed request/response models, dependency injection,
    tenant context, and consistent JSON error envelopes.
    """

    @abstractmethod
    def register(self) -> dict[str, object]:
        raise NotImplementedError
