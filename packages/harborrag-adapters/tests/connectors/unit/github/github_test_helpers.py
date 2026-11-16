"""Shared fake client and fixture builders for GitHub connector tests."""

from __future__ import annotations

from typing import Any

from harborrag_adapters.connectors import GitHubRepositoryConfig


class FakeGitHubClient:
    """GitHubClient that answers each endpoint's registered responses in order.

    A registered exception is raised instead of returned, and an endpoint with
    no response left fails the test.

    Attributes:
        responses: Responses still to return, by endpoint.
        calls: Every requested endpoint with its params, in order.
        response_limits: The ``max_bytes`` of every request, in order.
    """

    def __init__(self) -> None:
        self.responses: dict[str, list[Any]] = {}
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        self.response_limits: list[int | None] = []

    def add(self, endpoint: str, *responses: Any) -> None:
        """Queue responses for an endpoint, returned in the given order."""
        self.responses.setdefault(endpoint, []).extend(responses)

    def get_json(
        self,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        max_bytes: int | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Record the call and return or raise the endpoint's next response."""
        self.calls.append((endpoint, params))
        self.response_limits.append(max_bytes)
        values = self.responses.get(endpoint)
        if not values:
            raise AssertionError(f"Unexpected GitHub endpoint: {endpoint}")
        value = values.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def config(**overrides: Any) -> GitHubRepositoryConfig:
    """Return a config for the test repository with ``overrides`` applied."""
    values = {
        "repository_url": "https://github.com/acme/harbor-rag.git",
        "requests_per_minute": 6000,
        "allowed_extensions": [],
    }
    values.update(overrides)
    return GitHubRepositoryConfig(**values)


def repo() -> dict[str, Any]:
    """Return a repository payload whose default branch is ``main``."""
    return {
        "id": 42,
        "full_name": "acme/harbor-rag",
        "private": False,
        "default_branch": "main",
    }


def commit(ref: str = "commit1", tree_sha: str = "tree-root") -> dict[str, Any]:
    """Return a commit payload with sha ``ref`` and root tree ``tree_sha``."""
    return {
        "sha": ref,
        "html_url": f"https://github.com/acme/harbor-rag/commit/{ref}",
        "commit": {
            "message": "Update docs",
            "author": {
                "name": "Ada",
                "email": "ada@example.com",
                "date": "2024-05-24T20:57:56Z",
            },
            "committer": {
                "name": "Grace",
                "email": "grace@example.com",
                "date": "2024-05-24T21:00:00Z",
            },
            "tree": {"sha": tree_sha},
        },
    }


def tree_item(path: str, sha: str, size: int = 10) -> dict[str, Any]:
    """Return a tree item for a regular file."""
    return {
        "path": path,
        "mode": "100644",
        "type": "blob",
        "sha": sha,
        "size": size,
    }


def add_repo_and_commit(client: FakeGitHubClient) -> None:
    """Register the repository and its ``main`` commit on the fake client."""
    client.add("repos/acme/harbor-rag", repo())
    client.add("repos/acme/harbor-rag/commits/main", commit())
