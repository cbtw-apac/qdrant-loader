"""Unit tests for GitHub connector discovery (tree walk and explicit paths)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from github_test_helpers import (
    FakeGitHubClient,
    add_repo_and_commit,
    config,
    tree_item,
)

from harborrag_adapters.connectors import GitHubConnector
from harborrag_adapters.connectors.exceptions import DocumentProcessingError
from harborrag_adapters.connectors.github.repository_paths import guess_mime_type
from harborrag_adapters.connectors.schemas import ConnectorQuery

pytestmark = [pytest.mark.unit, pytest.mark.graybox]

ROOT_TREE_ENDPOINT = "repos/acme/harbor-rag/git/trees/tree-root"


def _add_root_tree(client: FakeGitHubClient, *items: dict[str, Any]) -> None:
    client.add(ROOT_TREE_ENDPOINT, {"sha": "tree-root", "truncated": False, "tree": list(items)})


def _add_scoped_tree(client: FakeGitHubClient) -> None:
    _add_root_tree(
        client,
        tree_item("README.md", "sha-readme"),
        tree_item("docs/guide.md", "sha-guide"),
        tree_item("docs/api/index.md", "sha-api"),
        tree_item("src/app.py", "sha-app"),
    )


def _discovered_paths(connector: GitHubConnector, query: ConnectorQuery) -> list[str]:
    return [record.metadata["path"] for record in connector.discover(query)]


def test_discover_path_and_pattern_query_returns_matching_tree_files() -> None:
    client = FakeGitHubClient()
    add_repo_and_commit(client)
    _add_root_tree(
        client,
        tree_item("README.md", "sha-readme"),
        tree_item("src/app.py", "sha-app"),
        tree_item("src/logo.png", "sha-logo"),
        tree_item("tests/test_app.py", "sha-test"),
    )
    connector = GitHubConnector(
        config(
            allowed_extensions={".md", ".py"},
            exclude_globs=["tests/*"],
            max_file_size_bytes=100,
        ),
        client=client,
    )

    records = list(connector.discover(ConnectorQuery(path="src", pattern="*.py")))

    assert [record.metadata["path"] for record in records] == ["src/app.py"]
    assert records[0].id == "github://acme/harbor-rag/src/app.py"
    assert records[0].checksum == "sha-app"
    assert records[0].source_type == guess_mime_type("src/app.py")
    assert client.calls[-1] == (ROOT_TREE_ENDPOINT, {"recursive": "1"})


def test_discover_truncated_recursive_tree_walks_subtrees() -> None:
    client = FakeGitHubClient()
    add_repo_and_commit(client)
    client.add(
        ROOT_TREE_ENDPOINT,
        {"sha": "tree-root", "truncated": True, "tree": []},
        {
            "sha": "tree-root",
            "tree": [
                {"path": "src", "type": "tree", "sha": "tree-src"},
                tree_item("README.md", "sha-readme"),
            ],
        },
    )
    client.add(
        "repos/acme/harbor-rag/git/trees/tree-src",
        {"sha": "tree-src", "tree": [tree_item("app.py", "sha-app")]},
    )
    connector = GitHubConnector(config(allowed_extensions={".py"}), client=client)

    records = list(connector.discover())

    assert [record.metadata["path"] for record in records] == ["src/app.py"]
    assert client.calls[2] == (ROOT_TREE_ENDPOINT, {"recursive": "1"})
    assert client.calls[3] == (ROOT_TREE_ENDPOINT, None)


def test_discover_explicit_file_paths_returns_content_records() -> None:
    client = FakeGitHubClient()
    add_repo_and_commit(client)
    client.add(
        "repos/acme/harbor-rag/contents/README.md",
        {"type": "file", "path": "README.md", "sha": "sha-readme", "size": 7},
    )
    connector = GitHubConnector(config(), client=client)

    records = list(connector.discover(ConnectorQuery(filters={"file_paths": ["README.md"]})))

    assert records[0].locator == "README.md"
    assert records[0].metadata["sha"] == "sha-readme"


def test_discover_explicit_file_paths_with_limit_stops_at_limit() -> None:
    client = FakeGitHubClient()
    add_repo_and_commit(client)
    client.add(
        "repos/acme/harbor-rag/contents/a.py",
        {"type": "file", "path": "a.py", "sha": "sha-a", "size": 1},
    )
    client.add(
        "repos/acme/harbor-rag/contents/b.py",
        {"type": "file", "path": "b.py", "sha": "sha-b", "size": 1},
    )
    connector = GitHubConnector(config(), client=client)
    query = ConnectorQuery(limit=1, filters={"file_paths": ["a.py", "b.py"]})

    assert _discovered_paths(connector, query) == ["a.py"]


def test_discover_explicit_path_filtered_out_continues_to_next_path() -> None:
    client = FakeGitHubClient()
    add_repo_and_commit(client)
    client.add(
        "repos/acme/harbor-rag/contents/logo.png",
        {"type": "file", "path": "logo.png", "sha": "sha-logo", "size": 5},
    )
    client.add(
        "repos/acme/harbor-rag/contents/README.md",
        {"type": "file", "path": "README.md", "sha": "sha-readme", "size": 7},
    )
    connector = GitHubConnector(config(excluded_extensions={".png"}), client=client)
    query = ConnectorQuery(filters={"file_paths": ["logo.png", "README.md"]})

    assert _discovered_paths(connector, query) == ["README.md"]


@pytest.mark.parametrize("alias", ["file_paths", "paths", "files"])
def test_discover_file_path_with_parent_segment_raises_before_any_request(alias: str) -> None:
    client = FakeGitHubClient()
    connector = GitHubConnector(config(), client=client)
    query = ConnectorQuery(filters={alias: ["../../other-repo/contents/x"]})

    with pytest.raises(ValueError, match=r"must not contain '\.\.' segments"):
        list(connector.discover(query))

    assert client.calls == []


def test_discover_file_path_outside_configured_root_raises_before_any_request() -> None:
    client = FakeGitHubClient()
    connector = GitHubConnector(config(root_path="docs"), client=client)
    query = ConnectorQuery(filters={"file_paths": ["docs/guide.md", "src/app.py"]})

    with pytest.raises(ValueError, match="inside the configured root path"):
        list(connector.discover(query))

    assert client.calls == []


def test_discover_file_path_inside_configured_root_returns_record() -> None:
    client = FakeGitHubClient()
    add_repo_and_commit(client)
    client.add(
        "repos/acme/harbor-rag/contents/docs/guide.md",
        {"type": "file", "path": "docs/guide.md", "sha": "sha-guide", "size": 7},
    )
    connector = GitHubConnector(config(root_path="docs"), client=client)
    query = ConnectorQuery(filters={"file_paths": ["docs/guide.md"]})

    assert _discovered_paths(connector, query) == ["docs/guide.md"]


def test_discover_file_path_through_symlink_to_other_file_raises() -> None:
    """GitHub answers a symlink with its target, here a file outside the root."""
    client = FakeGitHubClient()
    add_repo_and_commit(client)
    client.add(
        "repos/acme/harbor-rag/contents/docs/link.md",
        {"type": "file", "path": "src/notes.md", "sha": "sha-notes", "size": 7},
    )
    connector = GitHubConnector(config(root_path="docs"), client=client)
    query = ConnectorQuery(filters={"file_paths": ["docs/link.md"]})

    with pytest.raises(DocumentProcessingError, match="symlink") as raised:
        list(connector.discover(query))

    assert "src/notes.md" not in str(raised.value)


def test_discover_query_path_outside_configured_root_raises_before_any_request() -> None:
    client = FakeGitHubClient()
    connector = GitHubConnector(config(root_path="docs"), client=client)

    with pytest.raises(ValueError, match="inside the configured root path"):
        list(connector.discover(ConnectorQuery(path="src")))

    assert client.calls == []


@pytest.mark.parametrize("path", [None, "", "/", "."])
def test_discover_empty_query_path_uses_configured_root(path: str | None) -> None:
    client = FakeGitHubClient()
    add_repo_and_commit(client)
    _add_scoped_tree(client)
    connector = GitHubConnector(config(root_path="docs"), client=client)

    paths = _discovered_paths(connector, ConnectorQuery(path=path))

    assert paths == ["docs/guide.md", "docs/api/index.md"]


def test_discover_query_path_inside_configured_root_narrows_tree() -> None:
    client = FakeGitHubClient()
    add_repo_and_commit(client)
    _add_scoped_tree(client)
    connector = GitHubConnector(config(root_path="docs"), client=client)

    paths = _discovered_paths(connector, ConnectorQuery(path="docs/api"))

    assert paths == ["docs/api/index.md"]


def test_discover_commit_older_than_updated_after_returns_nothing() -> None:
    client = FakeGitHubClient()
    add_repo_and_commit(client)
    connector = GitHubConnector(config(), client=client)
    query = ConnectorQuery(updated_after=datetime(2099, 1, 1, tzinfo=UTC))

    assert _discovered_paths(connector, query) == []


def test_discover_commit_newer_than_updated_after_walks_tree() -> None:
    client = FakeGitHubClient()
    add_repo_and_commit(client)
    _add_root_tree(client, tree_item("a.py", "sha-a"))
    connector = GitHubConnector(config(), client=client)
    query = ConnectorQuery(updated_after=datetime(2000, 1, 1, tzinfo=UTC))

    assert _discovered_paths(connector, query) == ["a.py"]


def test_discover_non_recursive_query_skips_nested_paths() -> None:
    client = FakeGitHubClient()
    add_repo_and_commit(client)
    _add_root_tree(
        client,
        tree_item("README.md", "sha-readme"),
        tree_item("src/app.py", "sha-app"),
    )
    connector = GitHubConnector(config(), client=client)

    assert _discovered_paths(connector, ConnectorQuery(recursive=False)) == ["README.md"]


def test_discover_tree_walk_with_limit_stops_at_limit() -> None:
    client = FakeGitHubClient()
    add_repo_and_commit(client)
    _add_root_tree(client, tree_item("a.py", "sha-a"), tree_item("b.py", "sha-b"))
    connector = GitHubConnector(config(), client=client)

    assert _discovered_paths(connector, ConnectorQuery(limit=1)) == ["a.py"]


def test_discover_tree_walk_non_blob_entries_are_skipped() -> None:
    client = FakeGitHubClient()
    add_repo_and_commit(client)
    _add_root_tree(
        client,
        {"path": "src", "type": "tree", "sha": "tree-src"},
        tree_item("a.py", "sha-a"),
    )
    connector = GitHubConnector(config(), client=client)

    assert _discovered_paths(connector, ConnectorQuery()) == ["a.py"]
