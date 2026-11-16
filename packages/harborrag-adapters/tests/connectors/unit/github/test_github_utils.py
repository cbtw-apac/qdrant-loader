"""Unit tests for GitHub connector URL/path/endpoint utility helpers."""

from __future__ import annotations

import pytest

from harborrag_adapters.connectors.github.repository_paths import (
    blob_endpoint,
    commit_endpoint,
    content_endpoint,
    file_extension,
    github_raw_url,
    normalize_repo_path,
    parse_github_repository_url,
    path_in_scope,
    path_matches_query,
    tree_endpoint,
)

pytestmark = [pytest.mark.unit, pytest.mark.whitebox]

UNSAFE_OBJECT_IDS = [
    pytest.param("../../other-repo/git/blobs/abc", id="parent-segments"),
    pytest.param("a/b", id="slash"),
    pytest.param("sha\n", id="trailing-newline"),
    pytest.param("", id="empty"),
    pytest.param("abc?x=1", id="query"),
    pytest.param("abc#frag", id="fragment"),
    pytest.param("%2e%2e", id="percent-encoded-dots"),
    pytest.param("a.b", id="dot"),
]


def test_content_endpoint_path_with_space_percent_encodes() -> None:
    endpoint = content_endpoint("acme", "harbor-rag", "docs/Hello World.md")

    assert endpoint == "repos/acme/harbor-rag/contents/docs/Hello%20World.md"


def test_content_endpoint_parent_segment_raises_value_error() -> None:
    with pytest.raises(ValueError, match=r"must not contain '\.\.' segments"):
        content_endpoint("acme", "harbor-rag", "../../other-repo/contents/x")


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("../../other-repo/contents/x", id="leading"),
        pytest.param("docs/../../x", id="inner"),
        pytest.param("docs/..", id="trailing"),
        pytest.param("/../x", id="after-root-slash"),
        pytest.param("..\\secrets.txt", id="backslash"),
    ],
)
def test_normalize_repo_path_parent_segment_raises_value_error(path: str) -> None:
    with pytest.raises(ValueError, match=r"must not contain '\.\.' segments"):
        normalize_repo_path(path)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        pytest.param("./docs//guide.md", "docs/guide.md", id="dot-and-double-slash"),
        pytest.param("docs\\guide.md", "docs/guide.md", id="backslash"),
        pytest.param("/", "", id="root"),
        pytest.param(".", "", id="dot-is-root"),
        pytest.param("./", "", id="dot-slash-is-root"),
        pytest.param("docs/v1..v2.md", "docs/v1..v2.md", id="dots-inside-name"),
        pytest.param("...", "...", id="three-dots"),
    ],
)
def test_normalize_repo_path_safe_path_returns_posix_path(path: str, expected: str) -> None:
    assert normalize_repo_path(path) == expected


@pytest.mark.parametrize("object_id", UNSAFE_OBJECT_IDS)
def test_blob_endpoint_unsafe_object_id_raises_value_error(object_id: str) -> None:
    with pytest.raises(ValueError, match="one URL path segment"):
        blob_endpoint("acme", "harbor-rag", object_id)


@pytest.mark.parametrize("object_id", UNSAFE_OBJECT_IDS)
def test_tree_endpoint_unsafe_object_id_raises_value_error(object_id: str) -> None:
    with pytest.raises(ValueError, match="one URL path segment"):
        tree_endpoint("acme", "harbor-rag", object_id)


@pytest.mark.parametrize(
    "object_id",
    ["sha-readme", "tree_root", "commit1", "3f786850e387550fdab836ed7e6dc881de23001b"],
)
def test_object_endpoints_single_segment_id_build_endpoint(object_id: str) -> None:
    assert blob_endpoint("acme", "harbor-rag", object_id) == (
        f"repos/acme/harbor-rag/git/blobs/{object_id}"
    )
    assert tree_endpoint("acme", "harbor-rag", object_id) == (
        f"repos/acme/harbor-rag/git/trees/{object_id}"
    )


@pytest.mark.parametrize("ref", ["../../other-repo/commits/main", "main/../.."])
def test_commit_endpoint_parent_segment_ref_raises_value_error(ref: str) -> None:
    with pytest.raises(ValueError, match=r"must not contain '\.\.' segments"):
        commit_endpoint("acme", "harbor-rag", ref)


def test_commit_endpoint_branch_with_slash_keeps_slash() -> None:
    endpoint = commit_endpoint("acme", "harbor-rag", "feature/x")

    assert endpoint == "repos/acme/harbor-rag/commits/feature/x"


def test_parse_github_repository_url_without_scheme_raises_value_error() -> None:
    with pytest.raises(ValueError, match="absolute GitHub repository URL"):
        parse_github_repository_url("not-a-url")


def test_parse_github_repository_url_missing_repo_segment_raises_value_error() -> None:
    with pytest.raises(ValueError, match="must include owner and repository"):
        parse_github_repository_url("https://github.com/acme")


def test_parse_github_repository_url_ssh_missing_repo_segment_raises_value_error() -> None:
    with pytest.raises(ValueError, match="must include owner and repository"):
        parse_github_repository_url("git@github.com:acme")


def test_file_extension_name_without_dot_returns_empty() -> None:
    assert file_extension("README") == ""


def test_path_in_scope_path_equal_to_root_returns_true() -> None:
    assert path_in_scope("src", "src", recursive=True) is True


def test_path_in_scope_non_recursive_nested_path_returns_false() -> None:
    assert path_in_scope("src/pkg/app.py", "src", recursive=False) is False
    assert path_in_scope("src/app.py", "src", recursive=False) is True


def test_path_matches_query_plain_pattern_matches_substring() -> None:
    assert path_matches_query("src/app.py", "app") is True
    assert path_matches_query("src/app.py", "missing") is False


def test_github_raw_url_default_web_url_uses_raw_githubusercontent_host() -> None:
    url = github_raw_url(
        web_url="https://github.com",
        owner="acme",
        repo="harbor-rag",
        ref="main",
        path="src/app.py",
    )

    assert url == "https://raw.githubusercontent.com/acme/harbor-rag/main/src/app.py"


def test_github_raw_url_custom_web_url_uses_raw_path() -> None:
    url = github_raw_url(
        web_url="https://ghe.example.com",
        owner="acme",
        repo="harbor-rag",
        ref="main",
        path="src/app.py",
    )

    assert url == "https://ghe.example.com/acme/harbor-rag/raw/main/src/app.py"
