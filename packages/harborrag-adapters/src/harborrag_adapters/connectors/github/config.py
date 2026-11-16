"""Validated settings for one GitHub repository source.

Validation runs at construction and does no I/O. Owner and repository names go
into every REST endpoint, so each must be one URL path segment. The token stays
out of ``repr``.

Typical usage example:

    config = GitHubRepositoryConfig(repository_url="https://github.com/acme/docs")
    connector = GitHubConnector(config)
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from harborrag_adapters.connectors.file_filters import normalize_extension
from harborrag_adapters.connectors.limits import (
    DEFAULT_ALLOWED_EXTENSIONS,
    DEFAULT_MAX_DOCUMENT_BYTES,
)
from harborrag_adapters.connectors.policies.validation import (
    validate_http_tuning,
    validate_https_url,
    validate_non_negative_limit,
)

from .repository_paths import (
    DEFAULT_GITHUB_API_URL,
    DEFAULT_GITHUB_API_VERSION,
    DEFAULT_GITHUB_WEB_URL,
    parse_github_repository_url,
)

_REPOSITORY_SEGMENT = re.compile(r"[A-Za-z0-9_.-]+")
_DOT_SEGMENTS = frozenset({".", ".."})


@dataclass(slots=True)
class GitHubRepositoryConfig:
    """Settings for one GitHub repository source.

    The connector reads one resolved ref of one repository. Discovery applies
    every filter and size limit. Load checks the root path and size limit
    again, because a caller can pass it a record built by hand.

    Attributes:
        owner: User or organization that owns the repository, filled from
            ``repository_url`` when unset.
        repo: Repository name, filled from ``repository_url`` when unset.
        repository_url: HTTPS, SSH or git-style URL that names the repository.
        token: GitHub token, kept out of ``repr``.
        ref: Branch, tag or commit to read, exclusive with ``branch`` and
            ``commit_sha``.
        branch: Branch to read, exclusive with ``ref`` and ``commit_sha``.
        commit_sha: Commit to read, exclusive with ``ref`` and ``branch``.
            With all three unset, the default branch is read.
        root_path: Directory that bounds discovery and load, or empty for the
            whole repository.
        api_url: HTTPS REST API base URL, stored without a trailing slash.
        web_url: HTTPS web base URL for provenance links, stored without a
            trailing slash.
        api_version: Value of the ``X-GitHub-Api-Version`` header.
        allowed_extensions: Extensions to ingest, stored lowercase and
            dot-prefixed, or empty for every extension not excluded.
        excluded_extensions: Extensions never ingested, stored lowercase and
            dot-prefixed.
        include_paths: Directories to ingest from, or empty for every path.
        exclude_paths: Directories never ingested.
        include_globs: Globs a file path must match, or empty for every path.
        exclude_globs: Globs that exclude a file path.
        max_file_size_bytes: Largest file loaded, in bytes, or None to leave
            only GitHub's 100 MB blob limit.
        process_file_callback: Optional ``(path, size, mime_type)`` hook that
            returns whether to ingest a file and why.
        fail_on_error: Re-raise a ``process_file_callback`` error instead of
            logging it and skipping the file.
        requests_per_minute: Client-side request rate limit.
        request_timeout_seconds: Timeout of one HTTP request, in seconds.
        max_retries: Retries of a transient HTTP failure or rate limit.
        backoff_factor: Seconds before the first retry, doubled for each later
            one, when GitHub sends no retry header.
    """

    owner: str | None = None
    repo: str | None = None
    repository_url: str | None = None
    token: str | None = field(default=None, repr=False)
    ref: str | None = None
    branch: str | None = None
    commit_sha: str | None = None
    root_path: str | None = None
    api_url: str = DEFAULT_GITHUB_API_URL
    web_url: str = DEFAULT_GITHUB_WEB_URL
    api_version: str = DEFAULT_GITHUB_API_VERSION
    allowed_extensions: set[str] = field(default_factory=lambda: set(DEFAULT_ALLOWED_EXTENSIONS))
    excluded_extensions: set[str] = field(default_factory=set)
    include_paths: list[str] = field(default_factory=list)
    exclude_paths: list[str] = field(default_factory=list)
    include_globs: list[str] = field(default_factory=list)
    exclude_globs: list[str] = field(default_factory=list)
    max_file_size_bytes: int | None = DEFAULT_MAX_DOCUMENT_BYTES
    process_file_callback: Callable[[str, int, str], tuple[bool, str]] | None = None
    fail_on_error: bool = False
    requests_per_minute: int = 120
    request_timeout_seconds: float = 30.0
    max_retries: int = 3
    backoff_factor: float = 0.5

    def __post_init__(self) -> None:
        """Fill owner and repository from ``repository_url`` and validate settings.

        Raises:
            ValueError: A setting is invalid, such as a missing or unsafe owner
                or repository name, a non-HTTPS URL, or ``ref``, ``branch`` and
                ``commit_sha`` combined.
        """
        self.api_url = self.api_url.rstrip("/")
        self.web_url = self.web_url.rstrip("/")
        validate_https_url("api_url", self.api_url)
        validate_https_url("web_url", self.web_url)

        if self.repository_url and (not self.owner or not self.repo):
            owner, repo = parse_github_repository_url(self.repository_url)
            self.owner = self.owner or owner
            self.repo = self.repo or repo

        if not self.owner or not self.repo:
            raise ValueError("GitHub config requires owner/repo or repository_url")
        _require_repository_segment("owner", self.owner)
        _require_repository_segment("repo", self.repo)
        if self.ref and self.branch:
            raise ValueError("GitHub config accepts ref or branch, not both")
        if self.commit_sha and (self.ref or self.branch):
            raise ValueError("GitHub config accepts commit_sha or ref/branch, not both")
        validate_non_negative_limit("max_file_size_bytes", self.max_file_size_bytes)
        validate_http_tuning(
            requests_per_minute=self.requests_per_minute,
            request_timeout_seconds=self.request_timeout_seconds,
            max_retries=self.max_retries,
            backoff_factor=self.backoff_factor,
        )

        self.allowed_extensions = {normalize_extension(value) for value in self.allowed_extensions}
        self.excluded_extensions = {
            normalize_extension(value) for value in self.excluded_extensions
        }


def _require_repository_segment(field_name: str, value: str) -> None:
    """Reject an owner or repository name that is not one safe URL path segment.

    Args:
        field_name: Config field the value came from, named in the error.
        value: Owner or repository name. Never echoed in the error.

    Raises:
        ValueError: ``value`` holds a character other than letters, digits,
            ``.``, ``-`` or ``_``, or is ``.`` or ``..``.
    """
    if _REPOSITORY_SEGMENT.fullmatch(value) is None or value in _DOT_SEGMENTS:
        raise ValueError(
            f"GitHub config {field_name} must be one URL path segment of letters, "
            "digits, '.', '-' or '_', other than '.' or '..'"
        )
