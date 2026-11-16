"""GitHub REST operations for one configured repository.

Every endpoint comes from repository_paths, so no payload or record value
reaches a URL unchecked. Checking paths against the configured root is the
connector's job, not this module's.

Typical usage example:

    github = GitHubRepositoryAPI(config, client)
    commit = github.resolve_commit(github.resolve_repository())
"""

from __future__ import annotations

import base64
import binascii
import logging
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

from harborrag_adapters.connectors.exceptions import DocumentProcessingError, FetchError
from harborrag_adapters.connectors.schemas import ConnectorQuery
from harborrag_core.domain.source import SourceRecord

from .client import GitHubClient
from .config import GitHubRepositoryConfig
from .filters import should_process_file
from .mappers import build_source_record, tree_sha_from_commit
from .repository_paths import (
    GITHUB_BLOB_LIMIT_BYTES,
    blob_endpoint,
    commit_endpoint,
    content_endpoint,
    is_blob,
    is_tree,
    normalize_repo_path,
    repo_endpoint,
    require_git_object_id,
    tree_endpoint,
)

logger = logging.getLogger("harborrag.adapters.connectors.github")

_BASE64_LINE_CHARS = 60
_BLOB_RESPONSE_FIELDS_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class _CommitTree:
    """Blob shas that one commit's recursive tree listing holds, by path.

    Attributes:
        blob_shas: Blob sha of every file in the listing, by repository path.
        truncated: Whether GitHub cut the listing short, so a path missing
            from ``blob_shas`` may still exist in the commit.
    """

    blob_shas: Mapping[str, str]
    truncated: bool


class GitHubRepositoryAPI:
    """GitHub REST calls for the trees, contents and blobs of one repository.

    Repository metadata, the resolved commit and each commit's tree listing are
    fetched once and cached for the life of the instance.

    Args:
        config: Validated repository, ref, filter and size settings.
        client: GitHub HTTP client that sends every request.
    """

    def __init__(self, config: GitHubRepositoryConfig, client: GitHubClient) -> None:
        self.config = config
        self.client = client
        self.owner = str(config.owner)
        self.repo = str(config.repo)
        self._repository: dict[str, Any] | None = None
        self._commit: dict[str, Any] | None = None
        self._resolved_ref: str | None = None
        self._commit_trees: dict[str, _CommitTree] = {}

    @property
    def resolved_ref(self) -> str | None:
        """The ref read in this run, or None until resolve_commit runs."""
        return self._resolved_ref

    def iter_tree(self, tree_sha: str, *, recursive: bool) -> Iterator[dict[str, Any]]:
        """Yield Git tree items, walking subtrees one by one if GitHub truncates recursion.

        A tree response that is not a JSON object raises FetchError.

        Args:
            tree_sha: Tree object id from a commit or a parent tree.
            recursive: List every descendant, not only the direct entries.

        Yields:
            dict[str, Any]: Raw tree item whose ``path`` is relative to the
            repository root.
        """
        response = self._tree_response(tree_sha, recursive=recursive)
        if recursive and response.get("truncated"):
            logger.warning(
                "GitHub recursive tree for %s/%s was truncated; falling back to subtree traversal",
                self.owner,
                self.repo,
            )
            yield from self._walk_tree_non_recursive(tree_sha)
            return

        yield from response.get("tree", [])

    def blob_sha_at_commit(self, path: str, *, commit_sha: str) -> str | None:
        """Return the blob sha that a commit's tree holds at a path.

        The commit's tree listing is fetched once and cached. When GitHub
        truncates the listing and the path is not in it, the contents API is
        asked instead. That lookup raises DocumentProcessingError when the path
        is not a file or is a symlink to another file.

        Args:
            path: Normalized repository-relative file path.
            commit_sha: Commit whose tree to look the path up in.

        Returns:
            The blob sha at ``path``, or None when the commit has no file there.
        """
        require_git_object_id(commit_sha)
        commit_tree = self._commit_tree(commit_sha)
        blob_sha = commit_tree.blob_shas.get(path)
        if blob_sha is not None or not commit_tree.truncated:
            return blob_sha
        return self._contents_blob_sha(path, commit_sha=commit_sha)

    def load_blob(self, sha: str, *, known_size: int | None = None) -> bytes:
        """Fetch and decode a Git blob while enforcing GitHub and config limits.

        With ``known_size``, the configured size limit is checked before the
        request, so an oversized file is never downloaded.

        Args:
            sha: Blob object id.
            known_size: Size in bytes reported before the fetch, if any.

        Returns:
            The decoded blob bytes.

        Raises:
            FetchError: The blob response is not a JSON object.
            DocumentProcessingError: The blob exceeds the 100 MB REST API limit
                or ``max_file_size_bytes``, declares an invalid size or an
                encoding other than base64, or is not valid base64 of its
                declared size.
        """
        if known_size is not None:
            self.enforce_size_limit(sha, known_size)

        blob = self.client.get_json(
            blob_endpoint(self.owner, self.repo, sha),
            max_bytes=self._blob_response_limit(),
        )
        if not isinstance(blob, dict):
            raise FetchError("GitHub blob response was not an object")

        raw_size = blob.get("size")
        if isinstance(raw_size, bool) or not isinstance(raw_size, int) or raw_size < 0:
            raise DocumentProcessingError(f"GitHub blob {sha} returned an invalid size")
        size = raw_size
        if size > GITHUB_BLOB_LIMIT_BYTES:
            raise DocumentProcessingError(f"GitHub blob {sha} exceeds the 100 MB REST API limit")
        self.enforce_size_limit(sha, size)
        encoding = str(blob.get("encoding") or "")
        content = str(blob.get("content") or "")
        if encoding != "base64":
            raise DocumentProcessingError(
                f"GitHub blob {sha} returned unsupported encoding {encoding!r}"
            )
        try:
            normalized_content = content.translate(str.maketrans("", "", " \t\r\n"))
            decoded = base64.b64decode(normalized_content, validate=True)
        except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
            raise DocumentProcessingError(f"GitHub blob {sha} is not valid base64") from exc
        if len(decoded) != size:
            raise DocumentProcessingError(
                f"GitHub blob {sha} decoded size {len(decoded)} does not match declared size {size}"
            )
        return decoded

    def _blob_response_limit(self) -> int:
        """Return the largest blob response to accept, in bytes.

        The limit is the base64 size of the decoded-file limit plus two bytes
        per escaped line break, since GitHub wraps base64 every 60 characters.
        A fixed allowance covers the other response fields.
        """
        configured_limit = self.config.max_file_size_bytes
        decoded_limit = (
            GITHUB_BLOB_LIMIT_BYTES
            if configured_limit is None
            else min(configured_limit, GITHUB_BLOB_LIMIT_BYTES)
        )
        encoded_limit = 4 * ((decoded_limit + 2) // 3)
        line_break_overhead = 2 * ((encoded_limit + _BASE64_LINE_CHARS - 1) // _BASE64_LINE_CHARS)
        return encoded_limit + line_break_overhead + _BLOB_RESPONSE_FIELDS_BYTES

    def content_file_item(self, path: str, *, ref: str) -> dict[str, Any]:
        """Resolve one path through the contents API and normalize it as a blob.

        GitHub answers a symlink to a regular file with the target file, so a
        response for another path is rejected rather than read as the requested
        one.

        Args:
            path: Repository-relative file path.
            ref: Branch, tag or commit sha to read the path at.

        Returns:
            A tree-style blob item with the requested path and the sha and size
            GitHub reported.

        Raises:
            DocumentProcessingError: The path is not a file at ``ref``, or it
                resolves through a symlink to another file.
        """
        requested_path = normalize_repo_path(path)
        response = self.client.get_json(
            content_endpoint(self.owner, self.repo, requested_path),
            params={"ref": ref},
        )
        if not isinstance(response, dict) or not is_blob(response):
            raise DocumentProcessingError(f"GitHub path {path!r} is not a file")
        if normalize_repo_path(str(response.get("path") or "")) != requested_path:
            raise DocumentProcessingError("GitHub path resolves through a symlink to another file")
        return {
            "path": requested_path,
            "sha": response.get("sha"),
            "size": int(response.get("size") or 0),
            "mode": "100644",
            "type": "blob",
        }

    def source_record(
        self,
        item: dict[str, Any],
        *,
        ref: str,
        commit: dict[str, Any],
    ) -> SourceRecord:
        """Map a tree item and the commit it was read at to a source record."""
        return build_source_record(
            item,
            owner=self.owner,
            repo=self.repo,
            ref=ref,
            commit_sha=str(commit.get("sha") or ""),
            commit=commit,
        )

    def record_for_path(self, path: str) -> SourceRecord:
        """Resolve one repository path at the run's ref and return its source record.

        A path that is not a file, or a symlink to another file, raises
        DocumentProcessingError.

        Args:
            path: Repository-relative file path.

        Returns:
            The source record, tied to the resolved commit.
        """
        repository = self.resolve_repository()
        commit = self.resolve_commit(repository)
        ref = self.resolved_ref or str(commit.get("sha") or "")
        item = self.content_file_item(path, ref=ref)
        return self.source_record(item, ref=ref, commit=commit)

    def resolve_repository(self) -> dict[str, Any]:
        """Fetch and cache repository metadata needed for default branch lookup.

        Returns:
            The repository payload. Later calls return the cached one.

        Raises:
            FetchError: The response has no ``full_name``.
        """
        if self._repository is not None:
            return self._repository
        response = self.client.get_json(repo_endpoint(self.owner, self.repo))
        if not isinstance(response, dict) or not response.get("full_name"):
            raise FetchError("GitHub repository did not include full_name")
        self._repository = response
        return response

    def resolve_commit(self, repository: dict[str, Any]) -> dict[str, Any]:
        """Resolve and cache the commit this ingestion run reads.

        The configured commit sha, ref or branch is resolved, else the
        repository's default branch.

        Args:
            repository: Repository payload from resolve_repository.

        Returns:
            The commit payload. Later calls return the cached one.

        Raises:
            FetchError: No ref is configured and the repository has no default
                branch, or the commit response has no sha or root tree sha.
        """
        if self._commit is not None:
            return self._commit

        ref = (
            self.config.commit_sha
            or self.config.ref
            or self.config.branch
            or repository.get("default_branch")
        )
        if not ref:
            raise FetchError("GitHub repository did not include default_branch")

        response = self._fetch_commit(str(ref))
        self._commit = response
        self._resolved_ref = str(ref)
        return response

    def should_process_file(
        self,
        item: dict[str, Any],
        query: ConnectorQuery,
        *,
        commit: dict[str, Any],
    ) -> bool:
        """Return whether a tree or contents item passes the config and query filters."""
        return should_process_file(self.config, item, query, commit=commit)

    def enforce_size_limit(self, label: str, size: int) -> None:
        """Reject a file whose size exceeds ``max_file_size_bytes``.

        Args:
            label: Blob sha or repository path named in the error.
            size: File size in bytes. 0 means unknown and is not checked.

        Raises:
            DocumentProcessingError: ``size`` exceeds ``max_file_size_bytes``.
        """
        if self.config.max_file_size_bytes is None or not size:
            return
        if size > self.config.max_file_size_bytes:
            raise DocumentProcessingError(
                f"GitHub file {label!r} size {size} exceeds "
                f"max_file_size_bytes {self.config.max_file_size_bytes}"
            )

    def _fetch_commit(self, ref: str) -> dict[str, Any]:
        """Fetch the commit that a ref or sha names.

        A response without a sha or a root tree sha raises FetchError.
        """
        response = self.client.get_json(
            commit_endpoint(self.owner, self.repo, ref),
            params={"per_page": 1},
        )
        if not isinstance(response, dict) or not response.get("sha"):
            raise FetchError("GitHub commit response did not include sha")
        if not tree_sha_from_commit(response):
            raise FetchError("GitHub commit response did not include tree sha")
        return response

    def _commit_tree(self, commit_sha: str) -> _CommitTree:
        """Return a commit's cached blob listing, fetching it on first use."""
        cached = self._commit_trees.get(commit_sha)
        if cached is not None:
            return cached
        response = self._tree_response(self._root_tree_sha(commit_sha), recursive=True)
        truncated = bool(response.get("truncated"))
        if truncated:
            logger.warning(
                "GitHub recursive tree for %s/%s at commit %s was truncated; "
                "checking unlisted paths through the contents API",
                self.owner,
                self.repo,
                commit_sha,
            )
        commit_tree = _CommitTree(
            blob_shas={
                str(item.get("path") or ""): str(item.get("sha") or "")
                for item in response.get("tree", [])
                if is_blob(item)
            },
            truncated=truncated,
        )
        self._commit_trees[commit_sha] = commit_tree
        return commit_tree

    def _root_tree_sha(self, commit_sha: str) -> str:
        """Return a commit's root tree sha from GitHub's commit object.

        Reuses the resolved commit when it is that commit. The tree sha never
        comes from a source record.
        """
        commit = self._commit
        if commit is None or commit.get("sha") != commit_sha:
            commit = self._fetch_commit(commit_sha)
        return tree_sha_from_commit(commit)

    def _contents_blob_sha(self, path: str, *, commit_sha: str) -> str | None:
        """Return a path's blob sha at a commit from the contents API, or None on 404."""
        try:
            item = self.content_file_item(path, ref=commit_sha)
        except FetchError as exc:
            if exc.status_code == HTTPStatus.NOT_FOUND:
                return None
            raise
        return str(item.get("sha") or "") or None

    def _tree_response(self, tree_sha: str, *, recursive: bool) -> dict[str, Any]:
        """Fetch one Git tree object, with every descendant when ``recursive``.

        A response that is not a JSON object raises FetchError.
        """
        response = self.client.get_json(
            tree_endpoint(self.owner, self.repo, tree_sha),
            params={"recursive": "1"} if recursive else None,
        )
        if not isinstance(response, dict):
            raise FetchError("GitHub tree response was not an object")
        return response

    def _walk_tree_non_recursive(
        self,
        tree_sha: str,
        *,
        prefix: str = "",
    ) -> Iterator[dict[str, Any]]:
        """Walk a tree one subtree at a time when GitHub truncates its recursive listing.

        A stack of per-level iterators replaces recursion, so a very deep tree
        cannot overflow the Python call stack. Items come out depth-first, as
        a recursive walk would yield them.
        """
        stack: list[Iterator[dict[str, Any]]] = [self._tree_items(tree_sha, prefix)]
        while stack:
            try:
                item = next(stack[-1])
            except StopIteration:
                stack.pop()
                continue
            if is_tree(item):
                stack.append(self._tree_items(str(item.get("sha") or ""), str(item["path"])))
            else:
                yield item

    def _tree_items(self, tree_sha: str, prefix: str) -> Iterator[dict[str, Any]]:
        """Fetch and normalize the direct entries of one tree (no recursion)."""
        response = self._tree_response(tree_sha, recursive=False)
        for item in response.get("tree", []):
            path = normalize_repo_path(
                f"{prefix}/{item.get('path')}" if prefix else item.get("path")
            )
            yield {**item, "path": path}
