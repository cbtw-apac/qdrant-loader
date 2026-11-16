"""SharePoint connector for drive files and site pages.

Caller selectors are untrusted and may only narrow the configured scope. Item
and page IDs reach Graph only through the validated endpoints in
``drive_paths`` and ``pages``. Logs and error messages name items by ID, never
by file name or page title.

Typical usage example:

    config = SharePointSiteConfig(site_url=site_url, access_token=token)
    connector = SharePointConnector(config)
    documents = [connector.load(record) for record in connector.discover()]
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from collections.abc import Callable, Iterator
from typing import Any

from harborrag_adapters.connectors.base import BaseConnector
from harborrag_adapters.connectors.exceptions import (
    AuthorizationError,
    DocumentProcessingError,
    FetchError,
)
from harborrag_adapters.connectors.rate_limiting import ConnectorRateLimiter
from harborrag_adapters.connectors.schemas import (
    ConnectorCapabilities,
    ConnectorQuery,
    ConnectorSkip,
)
from harborrag_core.domain.raw_document import RawDocument
from harborrag_core.domain.source import SourceRecord

from .client import SharePointClient, _RequestsGraphClient
from .config import SharePointSiteConfig
from .config_validation import validate_drive_path
from .drive import SharePointDriveAPI
from .drive_paths import (
    drive_item_endpoint,
    is_drive_file,
    is_within_drive_path,
    item_mime_type,
    stored_payload,
)
from .mappers import (
    build_document_metadata,
    build_page_document_metadata,
    drive_item_id_from_record,
    is_page_record,
    page_id_from_record,
)
from .pages import SharePointPagesAPI, page_title, render_page_html
from .skips import (
    NOT_IN_ALLOWLIST,
    SharePointItemSkippedError,
    SharePointSkipRecorder,
    item_load_error,
    log_event,
    log_skip,
    skip_reason_for_error,
)

_TIME_FOR_SHAREPOINT_CONNECTOR_TESTS = time


class SharePointConnector(BaseConnector):
    """Connector for SharePoint document libraries and site pages through Graph.

    Discovery walks drive items in the configured scope and, with
    ``include_pages`` on, the site's modern pages. Skipped items are reported
    through ``skipped`` and never stop the run. Only failed authentication, an
    unreachable site, invalid config and an unsafe caller selector are fatal.

    Args:
        config: Validated site config that sets the crawl scope.
        client: Graph client to use, or ``None`` for a requests-based client.
        rate_limiter: The runtime's shared limiter, so all workers throttle one
            Graph app registration together.

    Attributes:
        provider_name: Provider key of this connector.
        capabilities: Supported features. ``pagination`` is off because paging
            would re-walk the drive tree for every page.
    """

    provider_name = "sharepoint"
    capabilities = ConnectorCapabilities(
        pagination=False,
        incremental_sync=True,
        full_sync=True,
        relationships=True,
    )

    def __init__(
        self,
        config: SharePointSiteConfig,
        *,
        client: SharePointClient | None = None,
        rate_limiter: ConnectorRateLimiter | None = None,
    ) -> None:
        self.config = config
        self.client = client or _RequestsGraphClient(config, rate_limiter=rate_limiter)
        self.run_id = uuid.uuid4().hex
        self._skips = SharePointSkipRecorder(self.run_id)
        self._drive = SharePointDriveAPI(self.client, config, skips=self._skips)
        self._pages = SharePointPagesAPI(self.client, config)

    def bind_run_id(self, run_id: str) -> None:
        """Tag this connector's structured logs with the caller's run ID."""
        self.run_id = run_id
        self._skips.run_id = run_id

    def connect(self) -> None:
        """Authenticate and resolve the site up front so bad credentials fail fast.

        The site is read even when ``site_id`` is configured. That read obtains
        a token and proves the app is granted the site before any traversal.
        """
        self._drive.verify_site_access(self._drive.resolve_site())

    def close(self) -> None:
        """Release the client session when the connector owns one."""
        close = getattr(self.client, "close", None)
        if callable(close):
            close()

    @property
    def skipped(self) -> tuple[ConnectorSkip, ...]:
        """Items the most recent discovery skipped, with their reasons."""
        return self._skips.skipped

    def discover(self, query: ConnectorQuery | None = None) -> Iterator[SourceRecord]:
        """Discover SharePoint records from IDs, folder traversal, and site pages.

        Pages are yielded before files, so a limited discovery still samples
        both kinds. Selectors that point into a drive return files only. Each
        record is yielded once, even when two selectors reach it.

        Args:
            query: Caller selectors and filters, or ``None`` for an empty query.

        Yields:
            SourceRecord: Each in-scope record once, up to ``query.limit``.
        """
        query = query or ConnectorQuery()
        self._ensure_connected()
        self._skips.reset()
        site = self._drive.resolve_site()
        if not self._site_allowed(site):
            self._log_discovery_summary(0)
            return
        drives = self._drive.resolve_drives(site)
        log_event(
            logging.INFO,
            "sharepoint.discovery_started",
            run_id=self.run_id,
            site_id=site.get("id"),
            drive_ids=[drive.get("id") for drive in drives],
            include_pages=self.config.include_pages,
        )

        seen: set[str] = set()
        for record in self._iter_records(site, drives, query):
            if record.id in seen:
                continue
            seen.add(record.id)
            yield record
            if query.limit is not None and len(seen) >= query.limit:
                break
        self._log_discovery_summary(len(seen))

    def _log_discovery_summary(self, discovered: int) -> None:
        """Log what one completed traversal found and declined, by reason."""
        skips = self._skips.counts_by_reason()
        log_event(
            logging.INFO,
            "sharepoint.discovery_summary",
            run_id=self.run_id,
            discovered=discovered,
            skipped=sum(skips.values()),
            skipped_by_reason=skips,
        )

    def _iter_records(
        self,
        site: dict[str, Any],
        drives: list[dict[str, Any]],
        query: ConnectorQuery,
    ) -> Iterator[SourceRecord]:
        """Yield records from the query's selectors, or from the configured scope.

        The caller's path is checked before any page or drive-item request.
        Records may repeat across selectors, and ``discover`` drops the repeats.
        """
        walk_path = self._walk_path(query)
        item_ids = self._item_ids_from_query(query) or list(self.config.item_ids or ())
        root_item_id = self._root_item_id_from_query(query)
        if (item_ids or root_item_id) and len(drives) != 1:
            raise ValueError("SharePoint item_ids and root_item_id need a single-drive scope")
        if self.config.include_pages and not (item_ids or root_item_id or query.path):
            yield from self._pages.walk_pages(site=site, query=query)

        for drive in drives:
            if item_ids:
                for item_id in item_ids:
                    yield from self._drive.records_from_item_id(
                        item_id,
                        site=site,
                        drive=drive,
                        query=query,
                    )
                continue
            if root_item_id:
                yield from self._drive.walk_selected_folder(
                    root_item_id,
                    site=site,
                    drive=drive,
                    query=query,
                )
                continue
            yield from self._drive.walk_children(
                site=site,
                drive=drive,
                query=query,
                path=walk_path,
            )

    def _walk_path(self, query: ConnectorQuery) -> str | None:
        """Return the drive path to walk, or ``None`` for the drive root.

        The caller's ``query.path`` is untrusted. It is validated like
        ``root_path`` and may only narrow it, compared segment by segment and
        ignoring case. Without a caller path, ``root_path`` is walked.
        """
        requested = validate_drive_path("SharePoint query path", query.path)
        if requested is None:
            return self.config.root_path
        if not is_within_drive_path(requested, self.config.root_path):
            raise ValueError("SharePoint query path must stay inside the configured root path")
        return requested

    def _site_allowed(self, site: dict[str, Any]) -> bool:
        """Check the tenant and site allowlists, recording a skip when rejected."""
        rejected = self._drive.allowlist.rejected_tenant()
        if rejected is not None:
            self._skips.record(
                NOT_IN_ALLOWLIST,
                f"tenant {rejected!r} is not in allowed_tenant_ids",
                path=rejected,
            )
            return False
        rejected = self._drive.allowlist.rejected_site(site)
        if rejected is not None:
            self._skips.record(
                NOT_IN_ALLOWLIST,
                f"site {rejected!r} is not in allowed_sites",
                url=rejected if "://" in rejected else None,
                path=rejected,
            )
            return False
        return True

    def load(self, record: SourceRecord) -> RawDocument:
        """Load one SharePoint record, either a site page as HTML or a drive file.

        An item that is skipped, deleted or still failing after retries raises
        one of the item errors from ``skips``.

        Args:
            record: Record from this connector's discovery or ``load_by_ids``.

        Returns:
            The page HTML or the file bytes, with SharePoint metadata.

        Raises:
            DocumentProcessingError: The record is a page and ``include_pages`` is off.
        """
        page = is_page_record(record)
        if page and not self.config.include_pages:
            raise DocumentProcessingError("SharePoint page loading is disabled")
        site = self._drive.resolve_site()
        self._require_allowed_site(site, record)
        if page:
            return self._load_page(record, site)
        return self._load_file(record, site)

    def _require_allowed_site(self, site: dict[str, Any], record: SourceRecord) -> None:
        """Refuse a load when the tenant or site is outside its allowlist.

        Args:
            site: Resolved site payload.
            record: Record being loaded; its locator identifies the skip.

        Raises:
            SharePointItemSkippedError: The tenant or site is not allowlisted.
        """
        allowlist = self._drive.allowlist
        rejected = allowlist.rejected_tenant()
        detail = f"tenant {rejected!r} is not in allowed_tenant_ids"
        if rejected is None:
            rejected = allowlist.rejected_site(site)
            detail = f"site {rejected!r} is not in allowed_sites"
        if rejected is not None:
            log_skip(NOT_IN_ALLOWLIST, item_id=record.locator, run_id=self.run_id)
            raise SharePointItemSkippedError(NOT_IN_ALLOWLIST, detail, item_id=record.locator)

    def _load_page(self, record: SourceRecord, site: dict[str, Any]) -> RawDocument:
        """Render one site page's text web parts as a single HTML document.

        A page with no text web parts still loads as its title alone, because
        the page exists and its title is searchable.

        Args:
            record: Page record from discovery.
            site: Resolved and allowed site payload.

        Returns:
            The rendered page HTML with page metadata.

        Raises:
            DocumentProcessingError: The record belongs to another site.
        """
        site_id = str(site.get("id"))
        record_site_id = record.metadata.get("site_id")
        if record_site_id is not None and str(record_site_id) != site_id:
            raise DocumentProcessingError(
                f"SharePoint page {record.id} belongs to site {record_site_id!r}, "
                f"outside configured site {site_id!r}"
            )
        page_id = page_id_from_record(record)
        page = self._fetch_or_skip(
            lambda: self._pages.get_page(site_id, page_id),
            item_id=page_id,
        )
        html, has_text = render_page_html(page)
        title = page_title(page)
        if not has_text:
            log_event(
                logging.INFO,
                "sharepoint.page_title_only",
                run_id=self.run_id,
                page_id=page_id,
                detail="page has no text web parts; loading its title only",
            )
        log_event(
            logging.INFO,
            "sharepoint.page_loading",
            run_id=self.run_id,
            page_id=page_id,
            site_id=site_id,
        )
        metadata = build_page_document_metadata(
            page,
            site=site,
            title=title,
            checksum=hashlib.sha256(html.encode("utf-8")).hexdigest(),
            has_text_content=has_text,
        )
        return RawDocument(
            id=record.id,
            source=str(page.get("webUrl") or record.id),
            content=html,
            content_type="text/html",
            metadata=metadata.to_dict(),
            raw=stored_payload(page),
        )

    def _load_file(self, record: SourceRecord, site: dict[str, Any]) -> RawDocument:
        """Download one SharePoint drive file as a raw document.

        Every root-path, allowlist, size, and extension check runs on the
        item's metadata before its content is requested, so an out-of-policy
        file is never downloaded.

        Args:
            record: File record from discovery or ``load_by_ids``.
            site: Resolved and allowed site payload.

        Returns:
            The file bytes with drive metadata.

        Raises:
            DocumentProcessingError: The item is not a downloadable file.
            SharePointItemSkippedError: The file is outside the path allowlist,
                too large, or of a declined extension.
        """
        item_id = drive_item_id_from_record(record)
        drive = self._record_drive(record, site, item_id)
        drive_id = str(drive.get("id"))
        item = self._fetch_or_skip(
            lambda: self._drive.get_item(drive_id, item_id),
            item_id=item_id,
        )
        self._drive.require_inside_root(item)

        if not is_drive_file(item):
            raise DocumentProcessingError(
                f"SharePoint drive item {item_id} is not a downloadable file"
            )
        declined = self._drive.declined_reason(item)
        if declined is not None:
            reason, detail = declined
            url = item.get("webUrl")
            log_skip(reason, item_id=item_id, run_id=self.run_id)
            raise SharePointItemSkippedError(reason, detail, item_id=item_id, url=url)

        log_event(
            logging.INFO,
            "sharepoint.file_loading",
            run_id=self.run_id,
            item_id=item_id,
            drive_id=drive_id,
        )
        content_endpoint = f"{drive_item_endpoint(drive_id, item_id)}/content"
        content = self._fetch_or_skip(
            lambda: self.client.get_bytes(content_endpoint),
            item_id=item_id,
            url=item.get("webUrl"),
        )
        metadata = build_document_metadata(
            item,
            site=site,
            drive=drive,
            checksum=hashlib.sha256(content).hexdigest(),
        )

        return RawDocument(
            id=record.id,
            source=str(item.get("webUrl") or item_id),
            content=content,
            content_type=item_mime_type(item),
            metadata=metadata.to_dict(),
            raw=stored_payload(item),
        )

    def _record_drive(
        self,
        record: SourceRecord,
        site: dict[str, Any],
        item_id: str,
    ) -> dict[str, Any]:
        """Return the in-scope drive a file record belongs to, or refuse it.

        Args:
            record: File record whose metadata may name its drive.
            site: Resolved and allowed site payload.
            item_id: The record's drive item ID, for the error message.

        Returns:
            The in-scope drive payload.

        Raises:
            DocumentProcessingError: The record names a drive outside the scope,
                or names none while the scope has several drives.
        """
        drives = self._drive.resolve_drives(site)
        record_drive_id = record.metadata.get("drive_id")
        if record_drive_id is None:
            if len(drives) != 1:
                raise DocumentProcessingError(
                    f"SharePoint item {item_id} has no drive_id and the scope has several drives"
                )
            return drives[0]
        drive = self._drive.drive_in_scope(site, str(record_drive_id))
        if drive is None:
            expected = [str(candidate.get("id")) for candidate in drives]
            raise DocumentProcessingError(
                f"SharePoint item {item_id} belongs to drive {str(record_drive_id)!r}, "
                f"outside configured drive {', '.join(repr(value) for value in expected)}"
            )
        return drive

    def _fetch_or_skip[T](
        self,
        fetch: Callable[[], T],
        *,
        item_id: str,
        url: str | None = None,
    ) -> T:
        """Run one item-level Graph call, turning item failures into typed load errors.

        Each item failure is logged as a skip, by item ID and reason, before its
        error is raised. ``url`` goes on the error only. Failures that are not
        about one item pass through.
        """
        try:
            return fetch()
        except (AuthorizationError, FetchError) as exc:
            reason = skip_reason_for_error(exc)
            if reason is None:
                raise
            log_skip(reason, item_id=item_id, run_id=self.run_id)
            raise item_load_error(reason, exc, item_id=item_id, url=url) from exc

    def load_by_ids(self, item_ids: list[str]) -> Iterator[RawDocument]:
        """Load files for callers that already have drive item IDs.

        Args:
            item_ids: Drive item IDs in the configured drive.

        Yields:
            RawDocument: One raw document per item ID, in order.
        """
        for item_id in item_ids:
            yield self.load(self._drive.record_for_item_id(item_id))

    @staticmethod
    def _item_ids_from_query(query: ConnectorQuery) -> list[str]:
        """Read caller item IDs from ``item_ids``, ``drive_item_ids`` or ``file_ids``."""
        values = (
            query.filters.get("item_ids")
            or query.filters.get("drive_item_ids")
            or query.filters.get("file_ids")
        )
        if values is None:
            return []
        if isinstance(values, str):
            return [values]
        return [str(value) for value in values]

    @staticmethod
    def _root_item_id_from_query(query: ConnectorQuery) -> str | None:
        """Read the caller's folder item ID from ``root_item_id`` or ``folder_item_id``."""
        value = query.filters.get("root_item_id") or query.filters.get("folder_item_id")
        return str(value) if value else None
