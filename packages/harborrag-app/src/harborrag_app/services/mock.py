from __future__ import annotations

from harborrag_runtime.composition import CompositionRoot

from harborrag_app.services.base import AppResponse, BaseAppService


class MockAppService(BaseAppService):
    def health(self) -> AppResponse:
        return AppResponse(True, {"diagnostics": CompositionRoot.local().diagnostics()})

    def ingest_once(self) -> AppResponse:
        return AppResponse(True, CompositionRoot.local().run_mock_ingestion())
