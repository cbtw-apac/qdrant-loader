"""Selection of the configured application service, free of API-only dependencies.

Runtime imports stay inside the functions so importing this module stays cheap.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..ports import BaseAppService

if TYPE_CHECKING:
    from harborrag_runtime.config.settings import RuntimeSettings

logger = logging.getLogger("harborrag.app.workflow_control.composition.selection")


def select_app_service() -> tuple[BaseAppService, str]:
    """Compose the app service for the API after checking the parser catalog.

    A missing catalog file is logged and left to ingestion to report, so an
    API without ingestion configuration still starts.

    Returns:
        The app service and the name of its composition mode.

    Raises:
        ParserConfigurationError: The parser catalog file exists but is invalid.
    """
    from harborrag_runtime.config import load_parser_catalog
    from harborrag_runtime.config.settings import RuntimeSettings

    settings = RuntimeSettings()
    if settings.parser_config_path.is_file():
        load_parser_catalog(settings.parser_config_path)
    else:
        logger.warning(
            "Parser catalog %s not found; skipping its startup check",
            settings.parser_config_path,
        )
    return _app_service_from(settings), "production"


def runtime_app_service() -> BaseAppService:
    """Compose the app service from environment settings, as the CLI does."""
    from harborrag_runtime.config.settings import RuntimeSettings

    return _app_service_from(RuntimeSettings())


def get_app_service() -> BaseAppService:
    """Compose the API's app service without reporting its composition mode."""
    service, _ = select_app_service()
    return service


def _app_service_from(settings: RuntimeSettings) -> BaseAppService:
    """Build the production composition and the app service on top of it."""
    from harborrag_runtime.composition import CompositionRoot

    from .service import AppService

    composition = CompositionRoot.production(settings)
    return AppService(composition, settings)
