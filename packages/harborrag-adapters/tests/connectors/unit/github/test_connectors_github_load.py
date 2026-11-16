"""Unit tests for GitHub connector document loading (blob fetch and decode)."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from typing import Any

import pytest
from github_test_helpers import (
    FakeGitHubClient,
    add_repo_and_commit,
    commit,
    config,
    repo,
    tree_item,
)

from harborrag_adapters.connectors import GitHubConnector
from harborrag_adapters.connectors.exceptions import DocumentProcessingError, FetchError
from harborrag_core.domain.source import SourceRecord

pytestmark = [pytest.mark.unit, pytest.mark.graybox]

ROOT_TREE_ENDPOINT = "repos/acme/harbor-rag/git/trees/tree-root"


def _blob(sha: str, content: bytes) -> dict[str, object]:
    return {
        "sha": sha,
        "size": len(content),
        "encoding": "base64",
        "content": base64.b64encode(content).decode("ascii"),
    }


def _readme_blob() -> dict[str, object]:
    return _blob("sha-readme", b"# Hello")


def _add_root_tree(
    client: FakeGitHubClient,
    *items: dict[str, Any],
    truncated: bool = False,
) -> None:
    client.add(
        ROOT_TREE_ENDPOINT,
        {"sha": "tree-root", "truncated": truncated, "tree": list(items)},
    )


def _record(path: str, sha: str, *, commit_sha: str | None = None) -> SourceRecord:
    metadata: dict[str, object] = {"path": path, "sha": sha, "size": 7}
    if commit_sha is not None:
        metadata["commit_sha"] = commit_sha
    return SourceRecord(
        f"github://acme/harbor-rag/{path}",
        "text/markdown",
        path,
        metadata=metadata,
        checksum=sha,
    )


def _blob_requested(client: FakeGitHubClient) -> bool:
    return any("/git/blobs/" in endpoint for endpoint, _ in client.calls)


def test_load_record_with_sha_decodes_blob_and_builds_metadata() -> None:
    """The loaded metadata stays JSON-serializable, commit datetimes included."""
    client = FakeGitHubClient()
    add_repo_and_commit(client)
    _add_root_tree(client, tree_item("README.md", "sha-readme"))
    client.add("repos/acme/harbor-rag/git/blobs/sha-readme", _readme_blob())
    connector = GitHubConnector(config(), client=client)

    document = connector.load(
        SourceRecord(
            "github://acme/harbor-rag/README.md",
            "text/markdown",
            "README.md",
            metadata={"path": "README.md", "sha": "sha-readme", "size": 7},
            checksum="sha-readme",
            updated_at=datetime(2024, 5, 24, tzinfo=UTC),
        )
    )

    assert document.content == b"# Hello"
    assert document.content_type == "text/markdown"
    assert document.source == "https://github.com/acme/harbor-rag/blob/main/README.md"
    assert document.metadata["source_system"] == "github"
    assert document.metadata["metadata_schema_version"] == 1
    assert document.metadata["record_id"] == "README.md"
    assert document.metadata["title"] == "README.md"
    assert document.metadata["owner"] == "acme"
    assert document.metadata["repo"] == "harbor-rag"
    assert document.metadata["path"] == "README.md"
    assert document.metadata["commit_author"]["name"] == "Ada"
    assert "repository" not in document.metadata
    assert "html_url" not in document.metadata
    assert "raw_url" not in document.metadata
    assert "commit_url" not in document.metadata
    assert document.metadata["commit_author"]["date"] == "2024-05-24T20:57:56+00:00"
    assert document.metadata["commit_committer"]["date"] == "2024-05-24T21:00:00+00:00"
    json.dumps(document.metadata)


def test_load_blob_over_max_file_size_raises_before_decode() -> None:
    client = FakeGitHubClient()
    add_repo_and_commit(client)
    _add_root_tree(client, tree_item("big.txt", "sha-big", size=99))
    client.add(
        "repos/acme/harbor-rag/git/blobs/sha-big",
        {
            "sha": "sha-big",
            "size": 99,
            "encoding": "base64",
            "content": base64.b64encode(b"too large").decode("ascii"),
        },
    )
    connector = GitHubConnector(config(max_file_size_bytes=10), client=client)

    with pytest.raises(DocumentProcessingError, match="max_file_size_bytes"):
        connector.load(
            SourceRecord(
                "github://acme/harbor-rag/big.txt",
                "text/plain",
                "big.txt",
                metadata={"path": "big.txt", "sha": "sha-big"},
            )
        )


def test_load_oversized_content_lookup_raises_without_fetching_blob() -> None:
    """No blob response is registered, so a blob fetch would fail with AssertionError."""
    client = FakeGitHubClient()
    add_repo_and_commit(client)
    client.add(
        "repos/acme/harbor-rag/contents/big.txt",
        {"type": "file", "path": "big.txt", "sha": "sha-big", "size": 99},
    )
    connector = GitHubConnector(config(max_file_size_bytes=10), client=client)

    with pytest.raises(DocumentProcessingError, match="max_file_size_bytes"):
        connector.load(
            SourceRecord(
                "github://acme/harbor-rag/big.txt",
                "text/plain",
                "big.txt",
                metadata={"path": "big.txt"},
            )
        )


def test_load_non_base64_blob_encoding_raises() -> None:
    client = FakeGitHubClient()
    add_repo_and_commit(client)
    _add_root_tree(client, tree_item("README.md", "sha-bad"))
    client.add(
        "repos/acme/harbor-rag/git/blobs/sha-bad",
        {"sha": "sha-bad", "size": 7, "encoding": "utf-8", "content": "bad"},
    )
    connector = GitHubConnector(config(), client=client)

    with pytest.raises(DocumentProcessingError, match="unsupported encoding"):
        connector.load(
            SourceRecord(
                "github://acme/harbor-rag/README.md",
                "text/markdown",
                "README.md",
                metadata={"path": "README.md", "sha": "sha-bad"},
            )
        )


def test_load_record_sha_with_path_segments_raises_before_fetching_blob() -> None:
    client = FakeGitHubClient()
    add_repo_and_commit(client)
    connector = GitHubConnector(config(), client=client)

    with pytest.raises(ValueError, match="one URL path segment"):
        connector.load(
            SourceRecord(
                "github://acme/harbor-rag/README.md",
                "text/markdown",
                "README.md",
                metadata={"path": "README.md", "sha": "../../other-repo/git/blobs/abc"},
            )
        )

    assert not any("/git/blobs/" in endpoint for endpoint, _ in client.calls)


def test_load_record_without_sha_resolves_sha_through_contents_api() -> None:
    client = FakeGitHubClient()
    add_repo_and_commit(client)
    client.add(
        "repos/acme/harbor-rag/contents/README.md",
        {"type": "file", "path": "README.md", "sha": "sha-readme", "size": 7},
    )
    client.add("repos/acme/harbor-rag/git/blobs/sha-readme", _readme_blob())
    connector = GitHubConnector(config(), client=client)

    document = connector.load(
        SourceRecord(
            "github://acme/harbor-rag/README.md",
            "text/markdown",
            "README.md",
            metadata={"path": "README.md"},
        )
    )

    assert document.content == b"# Hello"


def test_load_unresolvable_sha_raises() -> None:
    client = FakeGitHubClient()
    add_repo_and_commit(client)
    client.add(
        "repos/acme/harbor-rag/contents/missing.py",
        {"type": "file", "path": "missing.py", "sha": ""},
    )
    connector = GitHubConnector(config(), client=client)

    with pytest.raises(DocumentProcessingError, match="does not include a blob sha"):
        connector.load(
            SourceRecord(
                "github://acme/harbor-rag/missing.py",
                "text/plain",
                "missing.py",
                metadata={"path": "missing.py"},
            )
        )


def test_load_blob_size_mismatch_raises() -> None:
    client = FakeGitHubClient()
    add_repo_and_commit(client)
    _add_root_tree(client, tree_item("README.md", "sha-readme"))
    client.add(
        "repos/acme/harbor-rag/git/blobs/sha-readme",
        {
            "sha": "sha-readme",
            "size": 0,
            "encoding": "base64",
            "content": base64.b64encode(b"# Hello").decode("ascii"),
        },
    )
    connector = GitHubConnector(config(), client=client)

    with pytest.raises(DocumentProcessingError, match="does not match declared size"):
        connector.load(
            SourceRecord(
                "github://acme/harbor-rag/README.md",
                "text/markdown",
                "README.md",
                metadata={"path": "README.md", "sha": "sha-readme", "size": 0},
            )
        )


def test_load_record_outside_configured_root_raises_before_any_request() -> None:
    client = FakeGitHubClient()
    connector = GitHubConnector(config(root_path="docs"), client=client)
    record = SourceRecord(
        "github://acme/harbor-rag/src/app.py",
        "text/x-python",
        "src/app.py",
        metadata={"path": "src/app.py", "sha": "sha-app", "size": 7},
    )

    with pytest.raises(ValueError, match="inside the configured root path"):
        connector.load(record)

    assert client.calls == []


def test_load_by_paths_paths_inside_root_load_each_file() -> None:
    client = FakeGitHubClient()
    add_repo_and_commit(client)
    client.add(
        "repos/acme/harbor-rag/contents/README.md",
        {"type": "file", "path": "README.md", "sha": "sha-readme", "size": 7},
    )
    _add_root_tree(client, tree_item("README.md", "sha-readme"))
    client.add("repos/acme/harbor-rag/git/blobs/sha-readme", _readme_blob())
    connector = GitHubConnector(config(), client=client)

    documents = list(connector.load_by_paths(["README.md"]))

    assert [document.content for document in documents] == [b"# Hello"]


def test_load_by_paths_symlink_to_other_file_raises_before_fetching_blob() -> None:
    """GitHub answers a symlink with its target, whose path differs from the request."""
    client = FakeGitHubClient()
    add_repo_and_commit(client)
    client.add(
        "repos/acme/harbor-rag/contents/docs/link.md",
        {"type": "file", "path": "src/notes.md", "sha": "sha-notes", "size": 7},
    )
    _add_root_tree(
        client, tree_item("docs/link.md", "sha-link"), tree_item("src/notes.md", "sha-notes")
    )
    client.add("repos/acme/harbor-rag/git/blobs/sha-notes", _blob("sha-notes", b"# Notes"))
    connector = GitHubConnector(config(), client=client)

    with pytest.raises(DocumentProcessingError, match="symlink") as raised:
        list(connector.load_by_paths(["docs/link.md"]))

    assert "src/notes.md" not in str(raised.value)
    assert not _blob_requested(client)


def test_load_by_paths_path_outside_configured_root_raises_before_any_request() -> None:
    client = FakeGitHubClient()
    connector = GitHubConnector(config(root_path="docs"), client=client)

    with pytest.raises(ValueError, match="inside the configured root path"):
        list(connector.load_by_paths(["docs/guide.md", "src/app.py"]))

    assert client.calls == []


def test_load_by_paths_parent_segment_raises_before_any_request() -> None:
    client = FakeGitHubClient()
    connector = GitHubConnector(config(), client=client)

    with pytest.raises(ValueError, match=r"must not contain '\.\.' segments"):
        list(connector.load_by_paths(["../../other-repo/contents/x"]))

    assert client.calls == []


def test_load_record_with_blob_sha_from_outside_root_raises_before_fetching_blob() -> None:
    """A forged record pairs an in-root path with an out-of-root blob of its commit."""
    client = FakeGitHubClient()
    add_repo_and_commit(client)
    _add_root_tree(
        client,
        tree_item("docs/guide.md", "sha-guide"),
        tree_item("src/settings.py", "sha-settings"),
    )
    client.add("repos/acme/harbor-rag/git/blobs/sha-settings", _blob("sha-settings", b"DEBUG = 1"))
    connector = GitHubConnector(config(root_path="docs"), client=client)
    forged = _record("docs/guide.md", "sha-settings", commit_sha="commit1")

    with pytest.raises(DocumentProcessingError, match="does not match the tree of its commit"):
        connector.load(forged)

    assert not _blob_requested(client)


def test_load_record_path_absent_from_commit_tree_raises_before_fetching_blob() -> None:
    client = FakeGitHubClient()
    add_repo_and_commit(client)
    _add_root_tree(client, tree_item("README.md", "sha-readme"))
    client.add("repos/acme/harbor-rag/git/blobs/sha-removed", _blob("sha-removed", b"# Old"))
    connector = GitHubConnector(config(), client=client)

    with pytest.raises(DocumentProcessingError, match="does not match the tree of its commit"):
        connector.load(_record("docs/removed.md", "sha-removed", commit_sha="commit1"))

    assert not _blob_requested(client)


def test_load_discovered_record_after_branch_moved_verifies_against_record_commit() -> None:
    client = FakeGitHubClient()
    client.add("repos/acme/harbor-rag", repo())
    client.add("repos/acme/harbor-rag/commits/main", commit("commit2", tree_sha="tree-head"))
    client.add("repos/acme/harbor-rag/commits/commit1", commit())
    _add_root_tree(client, tree_item("README.md", "sha-readme"))
    client.add("repos/acme/harbor-rag/git/blobs/sha-readme", _readme_blob())
    connector = GitHubConnector(config(), client=client)

    document = connector.load(_record("README.md", "sha-readme", commit_sha="commit1"))

    endpoints = [endpoint for endpoint, _ in client.calls]
    assert document.content == b"# Hello"
    assert "repos/acme/harbor-rag/commits/commit1" in endpoints
    assert ROOT_TREE_ENDPOINT in endpoints
    assert "repos/acme/harbor-rag/git/trees/tree-head" not in endpoints


def test_load_many_records_of_one_commit_fetches_commit_tree_once() -> None:
    client = FakeGitHubClient()
    add_repo_and_commit(client)
    _add_root_tree(client, tree_item("a.md", "sha-a"), tree_item("b.md", "sha-b"))
    client.add("repos/acme/harbor-rag/git/blobs/sha-a", _blob("sha-a", b"A"))
    client.add("repos/acme/harbor-rag/git/blobs/sha-b", _blob("sha-b", b"B"))
    connector = GitHubConnector(config(), client=client)

    contents = [
        connector.load(_record("a.md", "sha-a", commit_sha="commit1")).content,
        connector.load(_record("b.md", "sha-b", commit_sha="commit1")).content,
    ]

    endpoints = [endpoint for endpoint, _ in client.calls]
    assert contents == [b"A", b"B"]
    assert [endpoint for endpoint in endpoints if "/git/trees/" in endpoint] == [ROOT_TREE_ENDPOINT]
    assert "repos/acme/harbor-rag/commits/commit1" not in endpoints


def test_load_record_missing_from_truncated_tree_matching_contents_sha_loads() -> None:
    client = FakeGitHubClient()
    add_repo_and_commit(client)
    _add_root_tree(client, truncated=True)
    client.add(
        "repos/acme/harbor-rag/contents/README.md",
        {"type": "file", "path": "README.md", "sha": "sha-readme", "size": 7},
    )
    client.add("repos/acme/harbor-rag/git/blobs/sha-readme", _readme_blob())
    connector = GitHubConnector(config(), client=client)

    document = connector.load(_record("README.md", "sha-readme"))

    assert document.content == b"# Hello"
    assert ("repos/acme/harbor-rag/contents/README.md", {"ref": "commit1"}) in client.calls


def test_load_record_missing_from_truncated_tree_other_contents_sha_raises() -> None:
    client = FakeGitHubClient()
    add_repo_and_commit(client)
    _add_root_tree(client, truncated=True)
    client.add(
        "repos/acme/harbor-rag/contents/README.md",
        {"type": "file", "path": "README.md", "sha": "sha-other", "size": 7},
    )
    client.add("repos/acme/harbor-rag/git/blobs/sha-readme", _readme_blob())
    connector = GitHubConnector(config(), client=client)

    with pytest.raises(DocumentProcessingError, match="does not match the tree of its commit"):
        connector.load(_record("README.md", "sha-readme", commit_sha="commit1"))

    assert not _blob_requested(client)


def test_load_record_missing_from_truncated_tree_contents_not_found_raises() -> None:
    client = FakeGitHubClient()
    add_repo_and_commit(client)
    _add_root_tree(client, truncated=True)
    client.add(
        "repos/acme/harbor-rag/contents/README.md",
        FetchError("GitHub request failed with HTTP 404: Not Found", status_code=404),
    )
    client.add("repos/acme/harbor-rag/git/blobs/sha-readme", _readme_blob())
    connector = GitHubConnector(config(), client=client)

    with pytest.raises(DocumentProcessingError, match="does not match the tree of its commit"):
        connector.load(_record("README.md", "sha-readme", commit_sha="commit1"))

    assert not _blob_requested(client)


@pytest.mark.parametrize("commit_sha", ["../../other-repo", "a/b", "commit1?x=1"])
def test_load_record_commit_sha_with_path_segments_raises_before_fetching_tree(
    commit_sha: str,
) -> None:
    client = FakeGitHubClient()
    add_repo_and_commit(client)
    _add_root_tree(client, tree_item("README.md", "sha-readme"))
    client.add("repos/acme/harbor-rag/git/blobs/sha-readme", _readme_blob())
    connector = GitHubConnector(config(), client=client)

    with pytest.raises(ValueError, match="one URL path segment"):
        connector.load(_record("README.md", "sha-readme", commit_sha=commit_sha))

    assert [endpoint for endpoint, _ in client.calls] == [
        "repos/acme/harbor-rag",
        "repos/acme/harbor-rag/commits/main",
    ]
