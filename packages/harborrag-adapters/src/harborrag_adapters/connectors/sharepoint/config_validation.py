"""Startup checks and normalizers for SharePoint connector configuration.

Checks are pure and never call Graph. A check on a value that goes into a URL
names the field and leaves the value out of its message.

Typical usage example:

    root_path = validate_drive_path("root_path", root_path)
    allowed_sites = normalize_allowlist("allowed_sites", allowed_sites)
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import cache
from urllib.parse import urlparse

from .drive_paths import normalize_drive_path, validate_graph_id_segment

_DNS_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_HOSTNAME = re.compile(rf"{_DNS_LABEL}(?:\.{_DNS_LABEL})*")
_MAX_HOSTNAME_LENGTH = 253
_SITE_ID = re.compile(r"[A-Za-z0-9.,_-]+")
_DOT_SEGMENTS = frozenset({".", ".."})
_SITE_PATH_RESERVED = frozenset("?#%:")
_DRIVE_ID_LABEL = "drive_id"


def validate_site_url(site_url: str) -> None:
    """Require an absolute HTTPS SharePoint site URL.

    Args:
        site_url: Configured site URL.

    Raises:
        ValueError: The URL is not ``https`` or has no hostname.
    """
    parsed = urlparse(site_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("site_url must be an absolute https:// SharePoint URL")


def validate_site_location(
    *,
    hostname: str | None,
    site_path: str | None,
    site_id: str | None,
    drive_id: str | None,
) -> None:
    """Reject site and drive values that could leave their Graph URL path segment.

    Each value goes into a Graph URL path unquoted, and an HTTP client collapses
    ``..`` segments, so an unchecked value could reach another site. An unset
    or empty value is not checked. The ``ValueError`` names the field and
    leaves the value out.

    Args:
        hostname: SharePoint host, a DNS host name of at most 253 characters.
        site_path: Site path below the host, ``/``-separated, without ``?``,
            ``#``, ``%`` or ``:``. Empty for the root site.
        site_id: Graph site ID such as ``host,siteCollectionGuid,siteGuid``,
            one segment of letters, digits, ``.``, ``,``, ``_`` or ``-``.
        drive_id: Graph drive ID, one segment of letters, digits, ``!``, ``_``
            or ``-``.
    """
    if hostname:
        _validate_hostname(hostname)
    if site_path:
        _validate_site_path(site_path)
    if site_id:
        _validate_site_id(site_id)
    if drive_id:
        validate_graph_id_segment(drive_id, label=_DRIVE_ID_LABEL)


def _validate_hostname(hostname: str) -> None:
    """Require dot-separated DNS labels of letters, digits and inner hyphens."""
    if len(hostname) > _MAX_HOSTNAME_LENGTH or not _HOSTNAME.fullmatch(hostname):
        raise ValueError(
            "hostname must be a DNS host name: dot-separated labels of letters, digits and '-'"
        )


def _validate_site_path(site_path: str) -> None:
    """Require a drive-path-like site path with no character that ends a URL path."""
    _require_clean_segments("site_path", site_path)
    if any(char in _SITE_PATH_RESERVED for char in site_path):
        raise ValueError("site_path must not contain '?', '#', '%' or ':'")


def _validate_site_id(site_id: str) -> None:
    """Require one URL path segment that is neither ``.`` nor ``..``."""
    if site_id in _DOT_SEGMENTS or not _SITE_ID.fullmatch(site_id):
        raise ValueError(
            "site_id must be one URL path segment of letters, digits, '.', ',', '_' or '-', "
            "other than '.' or '..'"
        )


def validate_positive_limit(name: str, value: int | None) -> None:
    """Reject a zero or negative size limit.

    Args:
        name: Config field name for the message.
        value: Configured limit, or ``None`` for no limit.

    Raises:
        ValueError: ``value`` is zero or negative.
    """
    if value is not None and value <= 0:
        raise ValueError(f"{name} must be greater than 0")


def validate_drive_path(name: str, value: str | None) -> str | None:
    """Normalize a drive-relative path and reject malformed ones.

    A backslash, a control character, or an empty, ``.`` or ``..`` segment
    raises ``ValueError``.

    Args:
        name: Config field or caller selector name for the message.
        value: Path to check, or ``None`` when unset.

    Returns:
        The path without surrounding slashes, or ``None`` for an unset or
        root (``/``) path.
    """
    if value is None:
        return None
    text = str(value)
    _require_clean_segments(name, text)
    return normalize_drive_path(text) or None


def _require_clean_segments(name: str, text: str) -> None:
    """Reject a backslash, a control character, or an empty, ``.`` or ``..`` segment."""
    if "\\" in text or any(ord(char) < 32 for char in text):
        raise ValueError(f"{name} must be a '/'-separated path")
    segments = text.strip("/").split("/") if text.strip("/") else []
    if any(segment in {"", *_DOT_SEGMENTS} for segment in segments):
        raise ValueError(f"{name} must not contain empty, '.' or '..' segments")


@cache
def supported_extensions() -> frozenset[str]:
    """Return every file extension the default parser families can read."""
    from harborrag_adapters.parsers.factory import HarborParserFactory

    registry = HarborParserFactory().create_registry()
    return frozenset(
        extension.lower() for parser in registry.families() for extension in parser.extensions
    )


def validate_extensions(allowed: set[str]) -> None:
    """Reject an empty allowlist and extensions no parser can extract.

    Args:
        allowed: Normalized extensions, such as ``.pdf``.

    Raises:
        ValueError: ``allowed`` is empty or names an extension no parser reads.
    """
    if not allowed:
        raise ValueError("allowed_extensions must list at least one extension")
    unknown = sorted(allowed - supported_extensions())
    if unknown:
        raise ValueError(f"allowed_extensions has unsupported extensions: {', '.join(unknown)}")


def validate_scope(
    *,
    item_ids: list[str] | None,
    crawl_all_drives: bool,
    drive_selected: bool,
    root_path: str | None,
) -> None:
    """Reject empty or contradictory crawl scopes.

    Args:
        item_ids: Explicit drive item IDs, or ``None`` when unset.
        crawl_all_drives: Whether the whole site is crawled.
        drive_selected: Whether ``drive_id`` or ``drive_name`` is set.
        root_path: Validated folder inside the drive.

    Raises:
        ValueError: ``item_ids`` is set but empty, ``crawl_all_drives`` is
            combined with a narrower scope, or both ``item_ids`` and
            ``root_path`` are set.
    """
    if item_ids is not None and not item_ids:
        raise ValueError("item_ids must list at least one item when set")
    if crawl_all_drives and (drive_selected or root_path or item_ids):
        raise ValueError(
            "crawl_all_drives covers the whole site; do not combine it with "
            "drive_id, drive_name, root_path, or item_ids"
        )
    if item_ids and root_path:
        raise ValueError("item_ids and root_path are separate scopes; set only one")


def normalize_allowlist(
    name: str,
    values: Iterable[str],
    *,
    allow_urls: bool = True,
) -> set[str]:
    """Normalize tenant or site allowlist entries for case-insensitive matching.

    Args:
        name: Config field name for the message.
        values: Entries. A single string counts as one entry.
        allow_urls: Whether an entry may be an HTTPS site URL.

    Returns:
        The entries trimmed and casefolded, without trailing slashes.
    """
    if isinstance(values, str):
        values = [values]
    normalized = set()
    for value in values:
        entry = str(value).strip()
        if not entry or any(char.isspace() for char in entry):
            raise ValueError(f"{name} entries must be non-empty identifiers")
        if "://" in entry:
            if not allow_urls:
                raise ValueError(f"{name} entries must be IDs, not URLs")
            validate_site_url(entry)
        normalized.add(normalize_identifier(entry))
    if not normalized:
        raise ValueError(f"{name} must list at least one entry when set")
    return normalized


def normalize_identifier(value: str) -> str:
    """Normalize a site ID, tenant ID, or site URL for allowlist comparison."""
    return value.strip().rstrip("/").casefold()


def normalize_path_prefixes(values: Iterable[str]) -> list[str]:
    """Normalize drive path prefixes for case-insensitive matching.

    An empty prefix (``/``) stands for the drive root.

    Args:
        values: Prefixes. A single string counts as one prefix.

    Returns:
        The casefolded prefixes without surrounding slashes.
    """
    if isinstance(values, str):
        values = [values]
    prefixes = []
    for value in values:
        normalized = validate_drive_path("allowed_path_prefixes", str(value))
        prefixes.append((normalized or "").casefold())
    if not prefixes:
        raise ValueError("allowed_path_prefixes must list at least one prefix when set")
    return prefixes
