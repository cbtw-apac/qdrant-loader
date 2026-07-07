from __future__ import annotations

from harborrag_app.services.base import BaseAppService
from harborrag_app.services.mock import MockAppService


def get_app_service() -> BaseAppService:
    # TODO: Replace this with dependency injection that returns the configured production service.
    return MockAppService()
