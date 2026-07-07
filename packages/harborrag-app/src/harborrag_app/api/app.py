from __future__ import annotations

from harborrag_app.api.dependencies import get_app_service


def create_app_state() -> dict[str, object]:
    """Framework-neutral app-state placeholder.

    TODO: Replace with create_app() returning a FastAPI app, attaching routers from api/routes,
    exception handlers, request context middleware, and health diagnostics.
    """
    return {"service": get_app_service().health().data}
