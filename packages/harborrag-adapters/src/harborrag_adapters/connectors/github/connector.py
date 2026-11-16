"""Connector that discovers and loads files from one GitHub repository.

Every caller-supplied path is checked against the configured root before any
GitHub request. A blob is loaded only after its commit's tree shows it at the
record's path, so a hand-built record cannot read a file outside the root.

Typical usage example:

    with GitHubConnector(config) as connector:
        documents = [connector.load(record) for record in connector.discover()]
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from typing import Any

from harborrag_adapters.connectors.base import BaseConnector
from harborrag_adapters.connectors.exceptions import DocumentProcessingError
from harborrag_adapters.connectors.schemas import ConnectorCapabilities, ConnectorQuery
from harborrag_core.domain.raw_document import RawDocument
from harborrag_core.domain.source import SourceRecord

from .client import GitHubClient, _RequestsGitHubClient
from .config import GitHubRepositoryConfig
from .filters import file_paths_from_query
from .mappers import (
    build_document_metadata,
    commit_timestamp,
    file_path_from_record,
    file_sha_from_record,
    tree_sha_from_commit,
)
from .repository import GitHubRepositoryAPI
from .repository_paths import (
    github_blob_url,
    guess_mime_type,
    is_blob,
    normalize_repo_path,
    path_in_scope,
    require_git_object_id,
)

logger = logging.getLogger("harborrag.adapters.connectors.github")


class GitHubConnector(BaseConnector):
    """Connector for the files of one GitHub repository, read over the REST API.

    Discovery walks the Git tree of one resolved commit. Load fetches each blob
    by sha, so content matches the discovered commit even after the branch
    moves.

    Args:
        config: Repository, ref, root path, filters and HTTP limits.
        client: GitHub HTTP client. Defaults to one built from ``config``.

    Attributes:
        provider_name: Name of the source provider.
        capabilities: Sync features this connector supports.
    """

    provider_name = "github"
    capabilities = ConnectorCapabilities(
        pagination=True,
        incremental_sync=True,
        full_sync=True,
        relationships=True,
        local_files=False,
    )

    def __init__(
        self,
        config: GitHubRepositoryConfig,
        *,
        client: GitHubClient | None = None,
    ) -> None:
        self.config = config
        self.owner = str(config.owner)
        self.repo = str(config.repo)
        self.client = client or _RequestsGitHubClient(config)
        self._github = GitHubRepositoryAPI(config, self.client)

    def connect(self) -> None:
        """Check that the API answers and the token can read the repository."""
        self._github.resolve_repository()

    def close(self) -> None:
        """Release the underlying GitHub HTTP client's resources."""
        close = getattr(self.client, "close", None)
        if callable(close):
            close()

    def discover(self, query: ConnectorQuery | None = None) -> Iterator[SourceRecord]:
        """Yield a record for each repository file that passes the filters.

        Explicit ``file_paths``, ``paths`` or ``files`` filters are looked up
        one by one. Otherwise the tree is walked under the query path, which can
        narrow the configured ``root_path`` but not leave it. An explicit path
        that is not a file, or a symlink to another file, raises
        DocumentProcessingError.

        Args:
            query: Caller query. ``None`` discovers everything under the
                configured root.

        Yields:
            SourceRecord: One record per file that passes the config and query
            filters, up to ``query.limit``.
        """
        query = query or ConnectorQuery()
        paths = file_paths_from_query(query)
        self._require_inside_root(paths)
        root_path = self._scoped_root_path(query)
        repository = self._github.resolve_repository()
        commit = self._github.resolve_commit(repository)
        ref = self._github.resolved_ref or str(commit.get("sha") or "")
        logger.info(
            "Discovering GitHub files in %s/%s at %s",
            self.owner,
            self.repo,
            ref,
        )

        if paths:
            yield from self._discover_paths(paths, query, ref=ref, commit=commit)
            return

        commit_updated_at = commit_timestamp(commit)
        if query.updated_after and commit_updated_at:
            if commit_updated_at <= query.updated_after:
                return

        yield from self._discover_tree(query, root_path=root_path, ref=ref, commit=commit)

    def _scoped_root_path(self, query: ConnectorQuery) -> str:
        """Return the query path as the directory to walk, or the configured root.

        An empty query path (``None``, ``""``, ``"/"`` or ``"."``) keeps the
        configured root.

        Args:
            query: Caller query whose ``path`` may narrow the configured root.

        Returns:
            The normalized directory to walk. ``""`` means the whole repository.
        """
        configured_root = normalize_repo_path(self.config.root_path)
        requested_root = normalize_repo_path(query.path)
        if not requested_root:
            return configured_root
        if not path_in_scope(requested_root, configured_root, recursive=True):
            raise ValueError("GitHub query path must stay inside the configured root path")
        return requested_root

    def _require_inside_root(self, paths: Sequence[str]) -> None:
        """Reject explicit file paths outside the configured root path.

        Args:
            paths: Repository-relative file paths a caller asked for.

        Raises:
            ValueError: A path is outside the configured root path or has a
                ``..`` segment.
        """
        root_path = self.config.root_path
        if not all(path_in_scope(path, root_path, recursive=True) for path in paths):
            raise ValueError("GitHub file paths must stay inside the configured root path")

    def _discover_paths(
        self,
        paths: Sequence[str],
        query: ConnectorQuery,
        *,
        ref: str,
        commit: dict[str, Any],
    ) -> Iterator[SourceRecord]:
        """Yield records for explicit paths that pass the filters, up to the limit."""
        yielded = 0
        for path in paths:
            item = self._github.content_file_item(path, ref=ref)
            if not self._github.should_process_file(item, query, commit=commit):
                continue
            yield self._github.source_record(item, ref=ref, commit=commit)
            yielded += 1
            if query.limit is not None and yielded >= query.limit:
                return

    def _discover_tree(
        self,
        query: ConnectorQuery,
        *,
        root_path: str,
        ref: str,
        commit: dict[str, Any],
    ) -> Iterator[SourceRecord]:
        """Yield records for tree files under ``root_path`` that pass the filters."""
        tree_sha = tree_sha_from_commit(commit)
        recursive = query.recursive or bool(root_path)
        yielded = 0
        for item in self._github.iter_tree(tree_sha, recursive=recursive):
            if not is_blob(item):
                continue
            if not path_in_scope(str(item.get("path") or ""), root_path, recursive=query.recursive):
                continue
            if not self._github.should_process_file(item, query, commit=commit):
                continue

            yield self._github.source_record(item, ref=ref, commit=commit)
            yielded += 1
            if query.limit is not None and yielded >= query.limit:
                return

    def load(self, record: SourceRecord) -> RawDocument:
        """Load one repository blob as a raw document.

        A record without a blob sha is looked up through the contents API.
        Otherwise the blob must match the tree of the record's commit
        (``metadata["commit_sha"]``, else the resolved commit) before it is
        fetched. Each commit's tree is fetched once per connector.

        Args:
            record: Source record from discover, or one built for a known path.

        Returns:
            The blob bytes with GitHub provenance metadata.

        Raises:
            DocumentProcessingError: The record's blob cannot be resolved or
                does not match its commit's tree, its path is not a file or is
                a symlink to another file, or the blob is too large or invalid.
        """
        path = file_path_from_record(record)
        self._require_inside_root([path])
        repository = self._github.resolve_repository()
        commit = self._github.resolve_commit(repository)
        ref = self._github.resolved_ref or str(commit.get("sha") or "")
        sha = file_sha_from_record(record)

        if not sha:
            item = self._github.content_file_item(path, ref=ref)
            sha = str(item.get("sha") or "")
        else:
            self._require_blob_in_commit(record, path=path, sha=sha, commit=commit)
            item = {
                "path": path,
                "sha": sha,
                "size": int(record.metadata.get("size") or 0),
                "mode": record.metadata.get("mode"),
            }

        if not sha:
            raise DocumentProcessingError(
                f"GitHub source record {record.id!r} does not include a blob sha"
            )
        known_size = int(item.get("size") or 0)
        self._github.enforce_size_limit(path, known_size)

        logger.info("Loading GitHub file %s/%s:%s", self.owner, self.repo, path)
        content = self._github.load_blob(sha, known_size=known_size or None)
        metadata = build_document_metadata(
            item,
            owner=self.owner,
            repo=self.repo,
            ref=ref,
            commit=commit,
            repository=repository,
        )
        if not metadata.size:
            metadata.size = len(content)
        source_url = github_blob_url(
            web_url=self.config.web_url,
            owner=self.owner,
            repo=self.repo,
            ref=ref,
            path=path,
        )

        return RawDocument(
            id=record.id,
            source=source_url,
            content=content,
            content_type=guess_mime_type(path),
            metadata=metadata.to_dict(),
            raw=item,
        )

    def _require_blob_in_commit(
        self,
        record: SourceRecord,
        *,
        path: str,
        sha: str,
        commit: dict[str, Any],
    ) -> None:
        """Reject a record whose blob is not the one its commit's tree holds at its path.

        The commit is the record's ``commit_sha``, else the resolved commit.
        The record's own ``tree_sha`` is never trusted.

        Args:
            record: Source record being loaded, named in the error.
            path: The record's normalized repository path.
            sha: The record's blob sha.
            commit: Commit resolved for this run.

        Raises:
            DocumentProcessingError: The commit's tree holds no blob or another
                blob at ``path``.
        """
        require_git_object_id(sha)
        commit_sha = str(record.metadata.get("commit_sha") or commit.get("sha") or "")
        if self._github.blob_sha_at_commit(path, commit_sha=commit_sha) != sha:
            raise DocumentProcessingError(
                f"GitHub source record {record.id!r} does not match the tree of its commit"
            )

    def load_by_paths(self, paths: Sequence[str]) -> Iterator[RawDocument]:
        """Load files for callers that already know their repository paths.

        Every path is checked against the configured ``root_path`` before the
        first request. A path that is not a file, or a symlink to another file,
        raises DocumentProcessingError.

        Args:
            paths: Repository-relative file paths.

        Yields:
            RawDocument: One raw document per path, in the given order.
        """
        self._require_inside_root(paths)
        for path in paths:
            yield self.load(self._github.record_for_path(path))
