"""SharePoint skip reasons, skip recording, item load errors and log entries.

Log entries carry only IDs, reason codes and counts, never an item's
``webUrl``, path, file name, page title or free-text detail, because a CV file
name usually holds the candidate's name. ``ConnectorSkip`` records and the
errors' ``url`` attributes keep the item's location as data for the caller.

Typical usage example:

    recorder = SharePointSkipRecorder(run_id)
    recorder.record(EXCEEDS_SIZE_LIMIT, detail, item_id=item_id)
    log_skip(ACCESS_DENIED, item_id=item_id, run_id=run_id)
"""

from __future__ import annotations

import json
import logging
from collections import Counter

from harborrag_adapters.connectors.exceptions import (
    AuthorizationError,
    DocumentProcessingError,
    FetchError,
    ItemNotFoundError,
    RateLimitError,
)
from harborrag_adapters.connectors.schemas import ConnectorSkip
from harborrag_core.ingestion import SourceRetriesExhaustedError, UnsupportedDocumentError

logger = logging.getLogger("harborrag.adapters.connectors.sharepoint")

NOT_IN_ALLOWLIST = "NOT_IN_ALLOWLIST"
UNSUPPORTED_EXTENSION = "UNSUPPORTED_EXTENSION"
EXCEEDS_SIZE_LIMIT = "EXCEEDS_SIZE_LIMIT"
DELETED = "DELETED"
ACCESS_DENIED = "ACCESS_DENIED"
EXTRACTION_FAILED = "EXTRACTION_FAILED"
TRANSIENT_ERROR_MAX_RETRIES = "TRANSIENT_ERROR_MAX_RETRIES"

_TRANSIENT_STATUS = {429, 500, 502, 503, 504}


class SharePointItemSkippedError(DocumentProcessingError, UnsupportedDocumentError):
    """A SharePoint item was skipped and will not be loaded.

    The run records it as a per-item failure and continues. Retrying does not
    help, because the skip reason stays the same until the item or the
    connector configuration changes.

    Args:
        reason: Skip reason code.
        detail: Why the item was skipped.
        item_id: Graph ID of the item, if known.
        url: The item's ``webUrl``, if known. Not included in the message.
    """

    def __init__(
        self,
        reason: str,
        detail: str,
        *,
        item_id: str | None = None,
        url: str | None = None,
    ) -> None:
        super().__init__(f"{reason}: {detail}")
        self.skip_reason = reason
        self.item_id = item_id
        self.url = url


class SharePointItemMissingError(ItemNotFoundError):
    """A SharePoint item was deleted or moved after discovery listed it.

    It counts as a missing source item, not as an unsupported document. Its
    ``skip_reason`` is ``DELETED``.

    Args:
        detail: Graph's error detail.
        item_id: Graph ID of the item, if known.
        url: The item's ``webUrl``, if known. Not included in the message.
    """

    def __init__(
        self,
        detail: str,
        *,
        item_id: str | None = None,
        url: str | None = None,
    ) -> None:
        super().__init__(f"{DELETED}: {detail}", status_code=404)
        self.skip_reason = DELETED
        self.item_id = item_id
        self.url = url


class SharePointItemUnavailableError(FetchError, SourceRetriesExhaustedError):
    """Graph still throttled or failed a SharePoint item after every retry.

    The run skips the item without retrying it again. It stays a transient
    failure, so a later run or a retry of failed documents picks it up. Its
    ``skip_reason`` is ``TRANSIENT_ERROR_MAX_RETRIES``.

    Args:
        detail: Graph's error detail.
        status_code: HTTP status of the last attempt, if known.
        item_id: Graph ID of the item, if known.
        url: The item's ``webUrl``, if known. Not included in the message.

    Attributes:
        retryable: Always ``False``, since ``max_retries`` already ran out.
    """

    retryable = False

    def __init__(
        self,
        detail: str,
        *,
        status_code: int | None = None,
        item_id: str | None = None,
        url: str | None = None,
    ) -> None:
        super().__init__(f"{TRANSIENT_ERROR_MAX_RETRIES}: {detail}", status_code=status_code)
        self.skip_reason = TRANSIENT_ERROR_MAX_RETRIES
        self.item_id = item_id
        self.url = url


def item_load_error(
    reason: str,
    error: Exception,
    *,
    item_id: str | None = None,
    url: str | None = None,
) -> Exception:
    """Return the typed error for one item that failed to load.

    Args:
        reason: Skip reason from ``skip_reason_for_error``.
        error: Graph failure for the item.
        item_id: Graph ID of the item, if known.
        url: The item's ``webUrl``, kept on the error for the caller.

    Returns:
        ``SharePointItemMissingError`` for ``DELETED``,
        ``SharePointItemUnavailableError`` for exhausted retries, and
        ``SharePointItemSkippedError`` for any other reason.
    """
    detail = str(error)
    if reason == DELETED:
        return SharePointItemMissingError(detail, item_id=item_id, url=url)
    if reason == TRANSIENT_ERROR_MAX_RETRIES:
        status_code = getattr(error, "status_code", None)
        return SharePointItemUnavailableError(
            detail, status_code=status_code, item_id=item_id, url=url
        )
    return SharePointItemSkippedError(reason, detail, item_id=item_id, url=url)


def skip_reason_for_error(error: Exception) -> str | None:
    """Map an item-level Graph failure to a skip reason.

    Args:
        error: Failure raised while fetching or listing one item.

    Returns:
        The skip reason, or ``None`` when the failure is not about one item.
        Callers re-raise those instead of skipping.
    """
    if isinstance(error, AuthorizationError):
        return ACCESS_DENIED
    if isinstance(error, RateLimitError):
        return TRANSIENT_ERROR_MAX_RETRIES
    if isinstance(error, FetchError):
        if error.status_code == 404:
            return DELETED
        if error.status_code in _TRANSIENT_STATUS:
            return TRANSIENT_ERROR_MAX_RETRIES
    return None


class SharePointSkipRecorder:
    """Collect the items one discovery traversal skipped, and log each by ID.

    Args:
        run_id: Run ID that tags every skip log entry. The connector may
            rebind it later.
    """

    def __init__(self, run_id: str | None = None) -> None:
        self.run_id = run_id
        self._skips: dict[tuple[str, str], ConnectorSkip] = {}

    @property
    def skipped(self) -> tuple[ConnectorSkip, ...]:
        """Skips in the order they were recorded."""
        return tuple(self._skips.values())

    def counts_by_reason(self) -> dict[str, int]:
        """Return how many items were skipped for each reason."""
        return dict(Counter(skip.reason for skip in self._skips.values()))

    def reset(self) -> None:
        """Forget skips from a previous traversal."""
        self._skips.clear()

    def record(
        self,
        reason: str,
        detail: str,
        *,
        item_id: str | None = None,
        url: str | None = None,
        path: str | None = None,
    ) -> None:
        """Record one skip and log its reason and item ID.

        Recording the same item and reason again does nothing.

        Args:
            reason: Skip reason code.
            detail: Why the item was skipped, kept on the ``ConnectorSkip`` only.
            item_id: Graph ID of the item, if known.
            url: The item's ``webUrl``, kept on the ``ConnectorSkip`` only.
            path: The item's drive path, or the rejected tenant or site, kept on
                the ``ConnectorSkip`` only.
        """
        identity = item_id or url or path or detail
        key = (identity, reason)
        if key in self._skips:
            return
        self._skips[key] = ConnectorSkip(
            path=path or url or item_id or "",
            reason=reason,
            detail=detail,
            item_id=item_id,
            url=url,
        )
        log_skip(reason, item_id=item_id, run_id=self.run_id)


def log_skip(reason: str, *, item_id: str | None = None, run_id: str | None = None) -> None:
    """Emit one ``sharepoint.item_skipped`` warning with the reason and item ID only.

    Args:
        reason: Skip reason code.
        item_id: Graph ID of the skipped item, if known.
        run_id: Run ID that tags the entry.
    """
    log_event(
        logging.WARNING,
        "sharepoint.item_skipped",
        run_id=run_id,
        skip_reason=reason,
        item_id=item_id,
    )


def log_event(level: int, event: str, *, run_id: str | None, **fields: object) -> None:
    """Emit one structured SharePoint log entry as a single JSON object.

    The same fields also go in ``extra`` with a ``sharepoint_`` prefix, so none
    collides with a ``LogRecord`` attribute.

    Args:
        level: ``logging`` level of the entry.
        event: Event name, such as ``sharepoint.discovery_summary``.
        run_id: Run ID that tags the entry.
        **fields: IDs, reason codes and counts only. Never a URL, path, name,
            title or document text.
    """
    payload = {"event": event, "run_id": run_id, **fields}
    extra = {f"sharepoint_{key}": value for key, value in payload.items()}
    logger.log(level, json.dumps(payload, default=str, sort_keys=True), extra=extra)
