"""SharePoint site, drive and drive-item traversal over Microsoft Graph.

Resolves the configured site and drives, walks folders, and applies the query,
allowlist, size and extension filters to drive items. An item selected by ID
must sit inside the configured ``root_path``. Item endpoints come from
``drive_paths``, which validates item IDs; nothing here downloads content.
Free-text log and error messages name items by ID, never by file name; the
structured skip fields owned by ``skips`` still carry ``webUrl`` and path.

Start from: SharePointDriveAPI.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from harborrag_adapters.connectors.exceptions import AuthorizationError, FetchError
from harborrag_adapters.connectors.schemas import ConnectorQuery
from harborrag_core.domain.source import SourceRecord

from .allowlist import SharePointAllowlist
from .client import SharePointClient
from .config import SharePointSiteConfig
from .drive_paths import (
    DRIVE_ITEM_SELECT,
    DRIVE_SELECT,
    children_endpoint,
    drive_item_endpoint,
    is_drive_file,
    is_drive_folder,
    is_within_drive_path,
    item_extension,
    item_has_drive_location,
    item_hidden,
    item_mime_type,
    item_name,
    item_path,
    matches_pattern,
    site_path_endpoint,
)
from .mappers import build_source_record, parse_timestamp
from .skips import (
    EXCEEDS_SIZE_LIMIT,
    NOT_IN_ALLOWLIST,
    UNSUPPORTED_EXTENSION,
    SharePointItemSkippedError,
    SharePointSkipRecorder,
    skip_reason_for_error,
)

logger = logging.getLogger("harborrag.adapters.connectors.sharepoint")
_MAX_PROVIDER_PAGES = 10_000
_OUTSIDE_ROOT_PATH = "SharePoint item must stay inside the configured root path"
PAGE_FILE_EXTENSION = ".aspx"


class SharePointDriveAPI:
    """SharePoint site, drive and drive-item traversal for one connector config.

    The resolved site, drive and drive list are cached for the instance's
    lifetime, so one instance serves one discovery or load session.

    Args:
        client: Graph client that sends the requests.
        config: Validated connector config that sets the crawl scope.
        skips: Recorder for declined items; a fresh one when ``None``.
    """

    def __init__(
        self,
        client: SharePointClient,
        config: SharePointSiteConfig,
        *,
        skips: SharePointSkipRecorder | None = None,
    ) -> None:
        self.client = client
        self.config = config
        self.skips = skips or SharePointSkipRecorder()
        self.allowlist = SharePointAllowlist(config)
        self._site: dict[str, Any] | None = None
        self._drive: dict[str, Any] | None = None
        self._drives: list[dict[str, Any]] | None = None

    def records_from_item_id(
        self,
        item_id: str,
        *,
        site: dict[str, Any],
        drive: dict[str, Any],
        query: ConnectorQuery,
    ) -> Iterator[SourceRecord]:
        """Yield records for a direct drive item ID, descending into folders.

        A direct item that is gone, forbidden, or still failing after retries
        is recorded as a skip so the other requested items still load. The
        ``ValueError`` for an unsafe ``item_id`` passes through from
        ``get_item``, the one for an item outside ``root_path`` from
        ``require_inside_root`` before anything is yielded or listed, and folder
        walk errors from ``walk_children``.

        Args:
            item_id: Drive item ID from config or the caller's query filters.
            site: Resolved site payload.
            drive: Resolved drive payload the item belongs to.
            query: Discovery query whose filters apply to every file.

        Yields:
            SourceRecord: One record for an accepted file, or one per accepted
            file below a folder.

        Raises:
            AuthorizationError: Fetching the item is denied for a reason that is
                not about this one item.
            FetchError: Fetching the item fails for a reason that is not about
                this one item.
        """
        try:
            item = self.get_item(str(drive["id"]), item_id)
        except (AuthorizationError, FetchError) as exc:
            reason = skip_reason_for_error(exc)
            if reason is None:
                raise
            self.skips.record(reason, str(exc), item_id=item_id)
            return
        self.require_inside_root(item)
        if is_drive_file(item):
            if self.should_process_file(item, query):
                yield build_source_record(
                    item,
                    site_id=str(site["id"]),
                    drive_id=str(drive["id"]),
                )
            return

        if is_drive_folder(item):
            yield from self.walk_children(
                site=site,
                drive=drive,
                query=query,
                item_id=item_id,
            )

    def walk_selected_folder(
        self,
        item_id: str,
        *,
        site: dict[str, Any],
        drive: dict[str, Any],
        query: ConnectorQuery,
    ) -> Iterator[SourceRecord]:
        """Walk a folder the caller selected by item ID, refusing one outside ``root_path``.

        With ``root_path`` set, the folder's metadata is fetched first and
        checked before any child is listed. With no ``root_path`` the folder is
        listed directly, without that lookup. Errors from ``get_item``,
        ``require_inside_root`` and ``walk_children`` pass through, including the
        ``ValueError`` for an unsafe ``item_id`` or a folder outside ``root_path``.

        Args:
            item_id: Folder item ID from the caller's query filters.
            site: Resolved site payload.
            drive: Resolved drive payload the folder belongs to.
            query: Discovery query whose filters apply to every file.

        Yields:
            SourceRecord: One record per accepted file below the folder.
        """
        if self.config.root_path:
            self.require_inside_root(self.get_item(str(drive["id"]), item_id))
        yield from self.walk_children(site=site, drive=drive, query=query, item_id=item_id)

    def require_inside_root(self, item: dict[str, Any]) -> None:
        """Refuse an item selected by ID that lies outside the configured ``root_path``.

        The item's drive path comes from its ``parentReference.path``. An item
        without that path resolves to its bare name, which could equal
        ``root_path`` by coincidence, so with ``root_path`` set it is refused
        rather than trusted. With no ``root_path`` every item in the drive
        passes.

        Args:
            item: Drive item payload fetched with ``DRIVE_ITEM_SELECT``.

        Raises:
            ValueError: ``root_path`` is set and the item has no drive
                location, or its drive path is neither ``root_path`` nor below it.
        """
        root_path = self.config.root_path
        if not root_path:
            return
        if not item_has_drive_location(item) or not is_within_drive_path(
            item_path(item), root_path
        ):
            raise ValueError(_OUTSIDE_ROOT_PATH)

    def walk_children(
        self,
        *,
        site: dict[str, Any],
        drive: dict[str, Any],
        query: ConnectorQuery,
        item_id: str | None = None,
        path: str | None = None,
    ) -> Iterator[SourceRecord]:
        """Walk child items depth-first with an explicit stack.

        The stack replaces recursion, so a very deep folder tree cannot exhaust
        the Python call stack before ``query.limit`` stops discovery, and the
        yield order stays depth-first.

        A subfolder whose listing fails for an item-level reason (deleted,
        access denied, retries exhausted) is recorded as a skip and the walk
        moves on, keeping whatever pages of it were already listed. The crawl
        root carries no folder item, so a failure listing it stays fatal:
        nothing in scope is reachable. The ``ValueError`` for an unsafe item
        ID passes through from ``children_endpoint``.

        Args:
            site: Resolved site payload.
            drive: Resolved drive payload to walk.
            query: Discovery query whose filters apply to every file.
            item_id: Folder item ID to start from; takes precedence over ``path``.
            path: Validated drive-relative folder path to start from; the drive
                root when both are unset.

        Yields:
            SourceRecord: One record per accepted file, in depth-first order.

        Raises:
            AuthorizationError: Listing the crawl root is denied, or a folder
                listing is denied for a reason that is not about that folder.
            FetchError: Listing the crawl root fails, or a folder listing fails
                for a reason that is not about that folder, such as a cycle.
        """
        drive_id = str(drive["id"])
        pending: list[tuple[str | None, str | None, dict[str, Any] | None]] = [
            (item_id, path, None)
        ]
        seen_folder_ids = {item_id} if item_id else set()
        while pending:
            current_item_id, current_path, folder = pending.pop()
            subfolders: list[tuple[str, dict[str, Any]]] = []
            try:
                for item in self.iter_children(
                    drive_id, item_id=current_item_id, path=current_path
                ):
                    if is_drive_file(item):
                        if self.should_process_file(item, query):
                            yield build_source_record(
                                item,
                                site_id=str(site["id"]),
                                drive_id=drive_id,
                            )
                        continue

                    child_id = self._folder_to_descend(item, query, seen_folder_ids)
                    if child_id:
                        subfolders.append((child_id, item))
            except (AuthorizationError, FetchError) as exc:
                if folder is None or not self._skip_failed_folder(folder, exc):
                    raise

            for child_id, child in reversed(subfolders):
                pending.append((child_id, None, child))

    def _skip_failed_folder(self, folder: dict[str, Any], error: Exception) -> bool:
        """Record a subfolder whose listing failed for an item-level reason.

        Returns ``False`` for a failure that is not about this one folder, such
        as a traversal cycle, so the caller re-raises it.
        """
        reason = skip_reason_for_error(error)
        if reason is None:
            return False
        self.skips.record(
            reason,
            f"folder listing failed: {error}",
            item_id=str(folder.get("id") or "") or None,
            url=folder.get("webUrl"),
            path=item_path(folder),
        )
        return True

    def _folder_to_descend(
        self,
        item: dict[str, Any],
        query: ConnectorQuery,
        seen_folder_ids: set[str],
    ) -> str | None:
        """Return a child folder ID to walk, or ``None`` when it is out of scope.

        A folder that cannot hold anything under an allowed path prefix is not
        listed at all, so nothing beneath it is fetched.

        Args:
            item: Child item from a folder listing.
            query: Discovery query; ``recursive=False`` stops the descent.
            seen_folder_ids: Folder IDs already queued; the returned ID is added.

        Returns:
            The folder's item ID, or ``None`` when it is not walked.

        Raises:
            FetchError: The folder was already queued, so the tree has a cycle.
        """
        if not (query.recursive and self.config.recursive and is_drive_folder(item)):
            return None
        child_id = str(item.get("id") or "")
        if not child_id:
            return None
        if not self.allowlist.folder_may_contain_allowed(item_path(item)):
            logger.debug("Skipping SharePoint folder %s outside allowed paths", child_id)
            return None
        if child_id in seen_folder_ids:
            raise FetchError("SharePoint folder traversal contains a cycle")
        seen_folder_ids.add(child_id)
        return child_id

    def iter_children(
        self,
        drive_id: str,
        *,
        item_id: str | None = None,
        path: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Iterate Graph children pages for a folder item, a folder path or the drive root.

        The ``ValueError`` for an unsafe ``item_id`` and Graph request errors
        pass through.

        Args:
            drive_id: Graph drive ID of the configured library.
            item_id: Folder item ID; takes precedence over ``path``.
            path: Validated drive-relative folder path.

        Yields:
            dict[str, Any]: Each child item payload, page by page.

        Raises:
            FetchError: A page link repeats, the page cap is reached, or a page
                holds an invalid ``value`` list.
        """
        endpoint = children_endpoint(drive_id, item_id=item_id, path=path)
        params: dict[str, Any] | None = {
            "$top": self.config.page_size,
            "$select": DRIVE_ITEM_SELECT,
        }
        seen_endpoints: set[str] = set()

        while endpoint:
            if endpoint in seen_endpoints or len(seen_endpoints) >= _MAX_PROVIDER_PAGES:
                raise FetchError("SharePoint children pagination did not advance")
            seen_endpoints.add(endpoint)
            response = self.client.get_json(endpoint, params=params)
            yield from _page_items(response, operation="children")
            next_link = response.get("@odata.nextLink")
            endpoint = str(next_link) if next_link else ""
            params = None

    def iter_site_drives(self, site_id: str) -> Iterator[dict[str, Any]]:
        """Iterate drives for a site when resolving a configured drive name.

        Graph request errors pass through.

        Args:
            site_id: Graph site ID.

        Yields:
            dict[str, Any]: Each drive payload, page by page.

        Raises:
            FetchError: A page link repeats, the page cap is reached, or a page
                holds an invalid ``value`` list.
        """
        endpoint = f"sites/{site_id}/drives"
        params: dict[str, Any] | None = {
            "$top": self.config.page_size,
            "$select": DRIVE_SELECT,
        }
        seen_endpoints: set[str] = set()

        while endpoint:
            if endpoint in seen_endpoints or len(seen_endpoints) >= _MAX_PROVIDER_PAGES:
                raise FetchError("SharePoint drive pagination did not advance")
            seen_endpoints.add(endpoint)
            response = self.client.get_json(endpoint, params=params)
            yield from _page_items(response, operation="drives")
            next_link = response.get("@odata.nextLink")
            endpoint = str(next_link) if next_link else ""
            params = None

    def get_item(self, drive_id: str, item_id: str) -> dict[str, Any]:
        """Fetch one drive item with the fields used by mappers and filters.

        The ``ValueError`` for an unsafe ``item_id`` is raised before any
        request; Graph request errors pass through.

        Args:
            drive_id: Graph drive ID of the configured library.
            item_id: Drive item ID from Graph, config or the caller.

        Returns:
            The drive item payload.
        """
        return self.client.get_json(
            drive_item_endpoint(drive_id, item_id),
            params={"$select": DRIVE_ITEM_SELECT},
        )

    def resolve_site(self) -> dict[str, Any]:
        """Resolve and cache the configured SharePoint site.

        A site denied to the app makes everything in scope unreachable, so the
        ``AuthorizationError`` is fatal for the run rather than a per-item skip.
        Other Graph request errors pass through.

        Returns:
            The site payload; a stub built from config when ``site_id`` is set.

        Raises:
            AuthorizationError: The app is not granted access to the site.
            FetchError: The site response has no ``id``.
        """
        if self._site is not None:
            return self._site

        if self.config.site_id:
            self._site = {
                "id": self.config.site_id,
                "name": self.config.hostname,
                "webUrl": self.config.site_url,
            }
            return self._site

        endpoint = site_path_endpoint(
            str(self.config.hostname),
            self.config.site_path,
        )
        try:
            site = self.client.get_json(endpoint)
        except AuthorizationError as exc:
            raise AuthorizationError(
                f"SharePoint app is not granted access to site {self.config.site_url or endpoint!r}; "
                "grant it Sites.Selected access to this site",
                status_code=403,
            ) from exc
        if not site.get("id"):
            raise FetchError("SharePoint site response did not include id")
        self._site = site
        logger.debug("Resolved SharePoint site %s", site.get("id"))
        return site

    def verify_site_access(self, site: dict[str, Any]) -> None:
        """Read a site configured by ``site_id`` once, so auth fails at startup.

        A site resolved from its URL was already read from Graph. One given by
        ID was not, so without this check bad credentials or a missing
        ``Sites.Selected`` grant would only surface mid-traversal. The site's
        ``webUrl`` is kept when the config did not supply one, which lets a
        URL entry in ``allowed_sites`` match a site configured by ID. Other
        Graph request errors pass through.

        Args:
            site: Resolved site payload; updated in place with ``webUrl``.

        Raises:
            AuthorizationError: The app is not granted access to the site.
        """
        if not self.config.site_id:
            return
        endpoint = f"sites/{self.config.site_id}"
        try:
            remote = self.client.get_json(endpoint, params={"$select": "id,webUrl,displayName"})
        except AuthorizationError as exc:
            raise AuthorizationError(
                f"SharePoint app is not granted access to site {self.config.site_id!r}; "
                "grant it Sites.Selected access to this site",
                status_code=403,
            ) from exc
        if not site.get("webUrl") and remote.get("webUrl"):
            site["webUrl"] = remote["webUrl"]

    def resolve_drive(self, site: dict[str, Any]) -> dict[str, Any]:
        """Resolve and cache the configured or default document library drive.

        Graph request errors pass through.

        Args:
            site: Resolved site payload.

        Returns:
            The drive payload; a stub built from config when ``drive_id`` is set.

        Raises:
            FetchError: No drive has the configured ``drive_name``, or the
                default drive response has no ``id``.
        """
        if self._drive is not None:
            return self._drive

        if self.config.drive_id:
            self._drive = {"id": self.config.drive_id, "name": self.config.drive_name}
            return self._drive

        site_id = str(site["id"])
        if self.config.drive_name:
            expected = self.config.drive_name.casefold()
            for drive in self.iter_site_drives(site_id):
                if str(drive.get("name") or "").casefold() == expected:
                    self._drive = drive
                    logger.debug("Resolved SharePoint drive %s", drive.get("id"))
                    return drive
            raise FetchError(f"SharePoint drive named {self.config.drive_name!r} was not found")

        drive = self.client.get_json(
            f"sites/{site_id}/drive",
            params={"$select": DRIVE_SELECT},
        )
        if not drive.get("id"):
            raise FetchError("SharePoint default drive response did not include id")
        self._drive = drive
        logger.debug("Resolved SharePoint default drive %s", drive.get("id"))
        return drive

    def resolve_drives(self, site: dict[str, Any]) -> list[dict[str, Any]]:
        """Resolve the drives in crawl scope: every document library, or one drive."""
        if not self.config.crawl_all_drives:
            return [self.resolve_drive(site)]
        if self._drives is None:
            self._drives = [
                drive
                for drive in self.iter_site_drives(str(site["id"]))
                if drive.get("id")
                and drive.get("driveType", "documentLibrary") == "documentLibrary"
            ]
            logger.debug("Resolved %d SharePoint document libraries", len(self._drives))
        return self._drives

    def drive_in_scope(self, site: dict[str, Any], drive_id: str) -> dict[str, Any] | None:
        """Return the in-scope drive with this ID, or ``None`` when it is outside."""
        for drive in self.resolve_drives(site):
            if str(drive.get("id")) == drive_id:
                return drive
        return None

    def should_process_file(self, item: dict[str, Any], query: ConnectorQuery) -> bool:
        """Apply query/config filters to one Microsoft Graph drive item.

        Query filters (``updated_after``, ``pattern``) and hidden files are
        intended filtering, not skips. An item declined for an allowlist, size,
        or extension reason is recorded as a skip with that reason.
        """
        if not self._matches_query(item, query):
            return False
        declined = self.declined_reason(item)
        if declined is not None:
            reason, detail = declined
            self.skips.record(
                reason,
                detail,
                item_id=str(item.get("id") or "") or None,
                url=item.get("webUrl"),
                path=item_path(item),
            )
            return False
        return self._callback_allows_file(item)

    def _matches_query(self, item: dict[str, Any], query: ConnectorQuery) -> bool:
        """Return whether a drive file passes the page, hidden and query filters.

        With ``include_pages`` on, an ``.aspx`` file in the Site Pages library
        is left to the pages API, so the drive walk never ingests the same page
        a second time under a file identity.
        """
        item_id = item.get("id")
        if self.config.include_pages and item_extension(item) == PAGE_FILE_EXTENSION:
            logger.debug("Skipping SharePoint page file %s; the pages API loads it", item_id)
            return False
        if item_hidden(item) and not self.config.include_hidden:
            logger.debug("Skipping hidden SharePoint file %s", item_id)
            return False
        if query.updated_after:
            updated_at = parse_timestamp(item.get("lastModifiedDateTime"))
            if updated_at and updated_at <= query.updated_after:
                return False
        return matches_pattern(item, query.pattern)

    def declined_reason(self, item: dict[str, Any]) -> tuple[str, str] | None:
        """Return the standard skip reason and detail for an out-of-policy file."""
        if not self.allowlist.path_allowed(item_path(item)):
            return NOT_IN_ALLOWLIST, "path is outside allowed_path_prefixes"
        size = int(item.get("size") or 0)
        limit = self.config.max_file_size_bytes
        if limit is not None and size > limit:
            return EXCEEDS_SIZE_LIMIT, f"size {size} exceeds max_file_size_bytes {limit}"
        extension = item_extension(item)
        if extension not in self.config.allowed_extensions:
            shown = extension or "<none>"
            return UNSUPPORTED_EXTENSION, f"extension {shown!r} is not allowed"
        if extension in self.config.excluded_extensions:
            return UNSUPPORTED_EXTENSION, f"extension {extension!r} is excluded"
        return None

    def _callback_allows_file(self, item: dict[str, Any]) -> bool:
        """Ask the configured ``process_file_callback`` whether to keep a file.

        A callback error is re-raised with ``fail_on_error`` on and otherwise
        logged against the item ID, declining the file.
        """
        callback = self.config.process_file_callback
        if callback is None:
            return True
        item_id = item.get("id")
        try:
            should_process, _ = callback(
                item_name(item), int(item.get("size") or 0), item_mime_type(item)
            )
        except Exception:
            if self.config.fail_on_error:
                raise
            logger.exception("SharePoint file callback failed for item %s", item_id)
            return False
        if not should_process:
            logger.debug("Skipping SharePoint file %s declined by process_file_callback", item_id)
            return False
        return True

    def enforce_size_limit(self, item: dict[str, Any]) -> None:
        """Refuse a drive file over ``max_file_size_bytes`` before it is downloaded.

        Args:
            item: Drive item payload with its ``size``.

        Raises:
            SharePointItemSkippedError: The file is larger than the configured limit.
        """
        size = int(item.get("size") or 0)
        if self.config.max_file_size_bytes is None or not size:
            return
        if size > self.config.max_file_size_bytes:
            item_id = str(item.get("id") or "") or None
            raise SharePointItemSkippedError(
                EXCEEDS_SIZE_LIMIT,
                f"SharePoint file {item_id} size {size} exceeds "
                f"max_file_size_bytes {self.config.max_file_size_bytes}",
                item_id=item_id,
                url=item.get("webUrl"),
            )

    def record_for_item_id(self, item_id: str) -> SourceRecord:
        """Resolve a drive item ID inside the configured root and build its source record.

        The ``ValueError`` for an unsafe ``item_id`` or an item outside
        ``root_path``, and Graph request errors, pass through.

        Args:
            item_id: Drive item ID from the caller.

        Returns:
            The item's source record in the configured drive.
        """
        site = self.resolve_site()
        drive = self.resolve_drive(site)
        item = self.get_item(str(drive["id"]), item_id)
        self.require_inside_root(item)
        return build_source_record(
            item,
            site_id=str(site["id"]),
            drive_id=str(drive["id"]),
        )


def _page_items(response: dict[str, Any], *, operation: str) -> list[dict[str, Any]]:
    """Validate a Graph collection page before exposing provider-controlled data.

    Args:
        response: One Graph collection page.
        operation: Listing name used in the error message.

    Returns:
        The page's item payloads.

    Raises:
        FetchError: ``value`` is not a list of objects.
    """
    raw_items = response.get("value", [])
    if not isinstance(raw_items, list) or any(not isinstance(item, dict) for item in raw_items):
        raise FetchError(f"SharePoint {operation} response contained an invalid value list")
    return raw_items
