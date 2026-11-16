"""Validated configuration for SharePoint site connectors.

``SharePointSiteConfig`` runs every startup check when it is built, so a
connector or Graph client can trust its values. It holds settings only and
never calls Graph.

Typical usage example:

    config = SharePointSiteConfig(site_url=site_url, access_token=token)
    connector = SharePointConnector(config)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from harborrag_adapters.connectors.file_filters import normalize_extension
from harborrag_adapters.connectors.limits import (
    DEFAULT_ALLOWED_EXTENSIONS as SHARED_ALLOWED_EXTENSIONS,
)
from harborrag_adapters.connectors.limits import DEFAULT_MAX_DOCUMENT_BYTES
from harborrag_adapters.connectors.policies.validation import (
    validate_http_tuning,
    validate_https_url,
    validate_non_negative_limit,
)

from .config_validation import (
    normalize_allowlist,
    normalize_path_prefixes,
    validate_drive_path,
    validate_extensions,
    validate_positive_limit,
    validate_scope,
    validate_site_location,
    validate_site_url,
)
from .delegated import default_token_cache_path
from .drive_paths import parse_sharepoint_site_url


class SharePointAuthMode(StrEnum):
    """Supported ways of obtaining Microsoft Graph tokens."""

    ACCESS_TOKEN = "access_token"
    CLIENT_CREDENTIALS = "client_credentials"
    DEVICE_CODE = "device_code"


DEFAULT_GRAPH_API_URL = "https://graph.microsoft.com/v1.0"
DEFAULT_MAX_FILE_SIZE_BYTES = DEFAULT_MAX_DOCUMENT_BYTES
DEFAULT_ALLOWED_EXTENSIONS = frozenset(SHARED_ALLOWED_EXTENSIONS)


@dataclass(slots=True)
class SharePointSiteConfig:
    """Settings for one SharePoint crawl scope, validated when built.

    The scope is a whole site, one document library, a folder in it, or
    explicit files. Site and drive values go into Graph URL paths unquoted, so
    each must stay inside its path segment. Delegated ``device_code`` access is
    never inferred and must be chosen explicitly.

    Attributes:
        site_url: Site URL, parsed into ``hostname`` and ``site_path``.
        hostname: SharePoint host name.
        site_path: Site path below the host, empty for the root site.
        site_id: Graph site ID, used instead of ``site_url``.
        drive_id: Document library to crawl, by Graph ID.
        drive_name: Document library to crawl, by name.
        root_path: Folder inside the library to crawl.
        item_ids: Drive item IDs to load instead of walking a folder.
        crawl_all_drives: Crawl every document library of the site.
        recursive: Walk subfolders too.
        allowed_tenant_ids: Allowed Microsoft tenant IDs, or ``None`` for any.
        allowed_sites: Allowed site IDs or URLs, or ``None`` for any.
        allowed_path_prefixes: Allowed drive path prefixes, or ``None`` for any.
        access_token: Pre-issued Graph token. Secret, kept out of ``repr``.
        tenant_id: Microsoft Entra tenant ID used to request tokens.
        client_id: Client ID of the app registration.
        client_secret: App secret for client credentials. Secret, kept out of ``repr``.
        auth_mode: How Graph tokens are obtained, inferred when unset.
        token_cache_path: Where the device-code refresh token is cached.
        harborrag_tenant_id: HarborRAG tenant that scopes the default token cache.
        graph_api_url: Microsoft Graph base URL, HTTPS only.
        allowed_extensions: File extensions to load.
        excluded_extensions: File extensions to skip.
        include_hidden: Also load items Graph marks hidden.
        include_pages: Also load the site's modern pages. Off by default.
        process_file_callback: Gets a file's name, size and MIME type and
            returns whether to load it, with a reason.
        max_file_size_bytes: Largest file to download, or ``None`` for no limit.
        fail_on_error: Re-raise a ``process_file_callback`` error instead of skipping.
        requests_per_minute: Graph request rate, from 1 to 6000.
        page_size: Items per Graph page, from 1 to 999.
        request_timeout_seconds: Timeout of one Graph request, in seconds.
        max_retries: Retries of one failed Graph request.
        backoff_factor: Base retry delay in seconds, doubled per attempt.
    """

    site_url: str | None = None
    hostname: str | None = None
    site_path: str | None = None
    site_id: str | None = None
    drive_id: str | None = None
    drive_name: str | None = None
    root_path: str | None = None
    item_ids: list[str] | None = None
    crawl_all_drives: bool = False
    recursive: bool = True
    allowed_tenant_ids: set[str] | None = None
    allowed_sites: set[str] | None = None
    allowed_path_prefixes: list[str] | None = None
    access_token: str | None = field(default=None, repr=False)
    tenant_id: str | None = None
    client_id: str | None = None
    client_secret: str | None = field(default=None, repr=False)
    auth_mode: SharePointAuthMode | str | None = None
    token_cache_path: str | None = None
    harborrag_tenant_id: str | None = None
    graph_api_url: str = DEFAULT_GRAPH_API_URL
    allowed_extensions: set[str] = field(default_factory=lambda: set(DEFAULT_ALLOWED_EXTENSIONS))
    excluded_extensions: set[str] = field(default_factory=set)
    include_hidden: bool = False
    include_pages: bool = False
    process_file_callback: Callable[[str, int, str], tuple[bool, str]] | None = None
    max_file_size_bytes: int | None = DEFAULT_MAX_FILE_SIZE_BYTES
    fail_on_error: bool = False
    requests_per_minute: int = 120
    page_size: int = 200
    request_timeout_seconds: float = 60.0
    max_retries: int = 3
    backoff_factor: float = 0.5

    def __post_init__(self) -> None:
        """Resolve site and auth shortcuts, then validate every setting.

        Raises:
            ValueError: A setting is missing, contradictory or unsafe.
        """
        self.graph_api_url = self.graph_api_url.rstrip("/")
        validate_https_url("graph_api_url", self.graph_api_url)

        if self.site_url:
            validate_site_url(self.site_url)
        if self.site_url and (not self.hostname or not self.site_path):
            hostname, site_path = parse_sharepoint_site_url(self.site_url)
            self.hostname = self.hostname or hostname
            self.site_path = self.site_path or site_path

        if not self.site_id and (not self.hostname or self.site_path is None):
            raise ValueError(
                "SharePoint config requires either site_id or site_url/hostname/site_path"
            )
        validate_site_location(
            hostname=self.hostname,
            site_path=self.site_path,
            site_id=self.site_id,
            drive_id=self.drive_id,
        )
        self._resolve_auth_mode()
        validate_http_tuning(
            requests_per_minute=self.requests_per_minute,
            request_timeout_seconds=self.request_timeout_seconds,
            max_retries=self.max_retries,
            backoff_factor=self.backoff_factor,
        )
        if not 1 <= self.page_size <= 999:
            raise ValueError("page_size must be between 1 and 999")
        validate_non_negative_limit("max_file_size_bytes", self.max_file_size_bytes)
        validate_positive_limit("max_file_size_bytes", self.max_file_size_bytes)
        self.root_path = validate_drive_path("root_path", self.root_path)

        self.allowed_extensions = {normalize_extension(value) for value in self.allowed_extensions}
        self.excluded_extensions = {
            normalize_extension(value) for value in self.excluded_extensions
        }
        validate_extensions(self.allowed_extensions)
        self._normalize_scope_and_allowlists()

    def _resolve_auth_mode(self) -> None:
        """Infer or parse ``auth_mode`` and require the credentials it needs."""
        if self.auth_mode is None:
            if self.access_token:
                self.auth_mode = SharePointAuthMode.ACCESS_TOKEN
            elif self.client_secret:
                self.auth_mode = SharePointAuthMode.CLIENT_CREDENTIALS
            else:
                raise ValueError("SharePoint config requires access_token or client credentials")
        try:
            self.auth_mode = SharePointAuthMode(str(self.auth_mode).strip().lower())
        except ValueError:
            modes = ", ".join(sorted(SharePointAuthMode))
            raise ValueError(f"auth_mode must be one of {modes}") from None

        if self.auth_mode == SharePointAuthMode.ACCESS_TOKEN and not self.access_token:
            raise ValueError("auth_mode access_token requires access_token")
        if self.auth_mode == SharePointAuthMode.CLIENT_CREDENTIALS and not (
            self.tenant_id and self.client_id and self.client_secret
        ):
            raise ValueError("SharePoint config requires access_token or client credentials")
        if self.auth_mode == SharePointAuthMode.DEVICE_CODE:
            if not (self.tenant_id and self.client_id):
                raise ValueError("auth_mode device_code requires tenant_id and client_id")
            if self.client_secret or self.access_token:
                raise ValueError("auth_mode device_code does not use client_secret or access_token")
            self.token_cache_path = str(self._token_cache())

    def _token_cache(self) -> Path:
        """Return where the device-code refresh token is cached.

        An explicit ``token_cache_path`` wins. Otherwise the default sits in the
        HarborRAG tenant's folder, so ``harborrag_tenant_id`` must be set.
        """
        if self.token_cache_path:
            return Path(self.token_cache_path).expanduser()
        if not self.harborrag_tenant_id:
            raise ValueError("auth_mode device_code needs token_cache_path or harborrag_tenant_id")
        return default_token_cache_path(
            self.harborrag_tenant_id, str(self.tenant_id), str(self.client_id)
        )

    def _normalize_scope_and_allowlists(self) -> None:
        """Trim ``item_ids``, reject contradictory scopes and normalize the allowlists."""
        if self.item_ids is not None:
            self.item_ids = [str(value).strip() for value in self.item_ids if str(value).strip()]
        validate_scope(
            item_ids=self.item_ids,
            crawl_all_drives=self.crawl_all_drives,
            drive_selected=bool(self.drive_id or self.drive_name),
            root_path=self.root_path,
        )
        if self.allowed_tenant_ids is not None:
            self.allowed_tenant_ids = normalize_allowlist(
                "allowed_tenant_ids", self.allowed_tenant_ids, allow_urls=False
            )
        if self.allowed_sites is not None:
            self.allowed_sites = normalize_allowlist("allowed_sites", self.allowed_sites)
        if self.allowed_path_prefixes is not None:
            self.allowed_path_prefixes = normalize_path_prefixes(self.allowed_path_prefixes)
