"""Filtering rules for GitHub repository discovery.

Decides whether one tree or contents item is ingested, from the connection's
configured filters and the caller's query filters. Configured filters are a
ceiling: a caller's allow and include lists only narrow them and a caller's
exclude lists only add to them, so a query can never widen what the
connection admits. No GitHub requests happen here; the optional
process-file callback is the only code that runs outside this module.

Entry points: should_process_file, file_paths_from_query.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from harborrag_adapters.connectors.file_filters import ExtensionFilter
from harborrag_adapters.connectors.query_values import normalized_string_list
from harborrag_adapters.connectors.schemas import ConnectorQuery

from .config import GitHubRepositoryConfig
from .mappers import commit_timestamp
from .repository_paths import (
    file_extension,
    guess_mime_type,
    normalize_repo_path,
    path_in_scope,
    path_matches_patterns,
    path_matches_query,
)

logger = logging.getLogger("harborrag.adapters.connectors.github")


def should_process_file(
    config: GitHubRepositoryConfig,
    item: dict[str, Any],
    query: ConnectorQuery,
    *,
    commit: dict[str, Any],
) -> bool:
    """Return whether a GitHub tree or contents item passes config and query filters.

    The configured extension, path and glob filters always apply; the query's
    filters of the same names can only narrow them. A ``..`` segment in the
    item path or in a caller path filter raises ValueError from
    normalize_repo_path. A process-file callback error is re-raised when
    ``fail_on_error`` is set and otherwise logged and treated as a rejection.

    Args:
        config: Connection config holding the configured filters and limits.
        item: Raw GitHub tree or contents item with ``path`` and ``size``.
        query: Caller query whose pattern, ``updated_after`` and filters narrow
            the selection.
        commit: Raw GitHub commit the run is anchored to, for ``updated_after``.

    Returns:
        True when the item should be ingested.
    """
    path = normalize_repo_path(str(item.get("path") or ""))
    size = int(item.get("size") or 0)
    extension = file_extension(path)

    if not _within_update_window(query, commit):
        return False
    if not path_matches_query(path, query.pattern):
        return False
    if not _extension_allowed(config, query, extension):
        return False
    if not _path_allowed(config, query, path):
        return False
    if not _glob_allowed(config, query, path):
        return False

    if config.max_file_size_bytes is not None and size > config.max_file_size_bytes:
        logger.debug("Skipping oversized GitHub file %s", path)
        return False
    return _callback_allows_file(config, path, size)


def file_paths_from_query(query: ConnectorQuery) -> list[str]:
    """Return the explicit file paths a query asks for, normalized.

    The first non-empty filter among ``file_paths``, ``paths`` and ``files``
    wins. A ``..`` segment raises ValueError from normalize_repo_path.

    Args:
        query: Caller query whose filters may hold explicit file paths as one
            string or a sequence.

    Returns:
        The normalized paths, or an empty list when the query names none.
    """
    values = (
        query.filters.get("file_paths") or query.filters.get("paths") or query.filters.get("files")
    )
    return [normalize_repo_path(value) for value in normalized_string_list(values, default=())]


def _within_update_window(query: ConnectorQuery, commit: dict[str, Any]) -> bool:
    if query.updated_after is None:
        return True
    updated_at = commit_timestamp(commit)
    return updated_at is None or updated_at > query.updated_after


def _extension_allowed(
    config: GitHubRepositoryConfig,
    query: ConnectorQuery,
    extension: str,
) -> bool:
    """Return whether an extension passes both the configured and the requested filters."""
    configured = ExtensionFilter.of(config.allowed_extensions, config.excluded_extensions)
    requested = ExtensionFilter.of(
        _requested_allowed_extensions(query),
        _requested_values(query, "excluded_extensions"),
    )
    return configured.rejection(extension) is None and requested.rejection(extension) is None


def _path_allowed(
    config: GitHubRepositoryConfig,
    query: ConnectorQuery,
    path: str,
) -> bool:
    """Return whether a path passes both the configured and the requested path roots.

    Every requested root is normalized before any is matched, so the ValueError
    of normalize_repo_path for a ``..`` segment never depends on which root
    matches first.
    """
    included = _requested_paths(query, "include_paths")
    excluded = _requested_paths(query, "exclude_paths")
    return _within_path_roots(
        path,
        included=config.include_paths,
        excluded=config.exclude_paths,
    ) and _within_path_roots(path, included=included, excluded=excluded)


def _glob_allowed(
    config: GitHubRepositoryConfig,
    query: ConnectorQuery,
    path: str,
) -> bool:
    """Return whether a path passes both the configured and the requested globs.

    Every requested glob is normalized before any is matched, so the ValueError
    of normalize_repo_path for a ``..`` segment never depends on which glob
    matches first.
    """
    included = _requested_paths(query, "include_globs")
    excluded = _requested_paths(query, "exclude_globs")
    return _matches_globs(
        path,
        included=config.include_globs,
        excluded=config.exclude_globs,
    ) and _matches_globs(path, included=included, excluded=excluded)


def _within_path_roots(path: str, *, included: Sequence[str], excluded: Sequence[str]) -> bool:
    """Return whether a path is under an included root (any, when none) and no excluded root."""
    is_included = not included or any(
        path_in_scope(path, root, recursive=True) for root in included
    )
    is_excluded = any(path_in_scope(path, root, recursive=True) for root in excluded)
    return is_included and not is_excluded


def _matches_globs(path: str, *, included: Sequence[str], excluded: Sequence[str]) -> bool:
    """Return whether a path matches an included glob (any, when none) and no excluded glob."""
    is_included = not included or path_matches_patterns(path, included)
    return is_included and not path_matches_patterns(path, excluded)


def _requested_allowed_extensions(query: ConnectorQuery) -> list[str]:
    """Return the caller's allowed extensions; ``extensions`` is read when the key is absent."""
    values = query.filters.get("allowed_extensions")
    if values is None:
        values = query.filters.get("extensions")
    return normalized_string_list(values, default=())


def _requested_values(query: ConnectorQuery, key: str) -> list[str]:
    """Return one caller filter as a list of strings, empty when the query omits it."""
    return normalized_string_list(query.filters.get(key), default=())


def _requested_paths(query: ConnectorQuery, key: str) -> list[str]:
    """Return one caller path or glob filter with every entry normalized.

    A ``..`` segment in any entry raises ValueError from normalize_repo_path.
    """
    return [normalize_repo_path(value) for value in _requested_values(query, key)]


def _callback_allows_file(
    config: GitHubRepositoryConfig,
    path: str,
    size: int,
) -> bool:
    if not config.process_file_callback:
        return True
    try:
        should_process, reason = config.process_file_callback(
            path,
            size,
            guess_mime_type(path),
        )
    except Exception:
        if config.fail_on_error:
            raise
        logger.exception("GitHub file callback failed for %s", path)
        return False
    if not should_process:
        logger.debug("Skipping GitHub file %s: %s", path, reason)
    return should_process
