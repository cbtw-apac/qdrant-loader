"""Unit tests for GitHub connector configuration and resource lifecycle."""

from __future__ import annotations

import pytest
from github_test_helpers import FakeGitHubClient, config

from harborrag_adapters.connectors import GitHubConnector, GitHubRepositoryConfig
from harborrag_adapters.connectors.github.repository_paths import parse_github_repository_url

pytestmark = [pytest.mark.unit, pytest.mark.graybox]

UNSAFE_REPOSITORY_SEGMENTS = [
    pytest.param("ac/me", id="slash"),
    pytest.param("..", id="parent"),
    pytest.param(".", id="current"),
    pytest.param("acme?x=1", id="query"),
    pytest.param("acme#x", id="fragment"),
    pytest.param("ac%2Fme", id="percent"),
    pytest.param("ac me", id="space"),
    pytest.param("acme\n", id="trailing-newline"),
]


def test_config_repository_url_sets_owner_and_repo_and_normalizes_extensions() -> None:
    cfg = config(allowed_extensions={"py", ".MD"}, excluded_extensions={"png"})

    assert cfg.owner == "acme"
    assert cfg.repo == "harbor-rag"
    assert cfg.allowed_extensions == {".py", ".md"}
    assert cfg.excluded_extensions == {".png"}
    assert parse_github_repository_url("git@github.com:acme/harbor-rag.git") == (
        "acme",
        "harbor-rag",
    )


def test_close_client_with_close_calls_it() -> None:
    client = FakeGitHubClient()
    closed: list[bool] = []
    client.close = lambda: closed.append(True)
    connector = GitHubConnector(config(), client=client)

    connector.close()

    assert closed == [True]


def test_close_client_without_close_does_not_raise() -> None:
    connector = GitHubConnector(config(), client=FakeGitHubClient())

    connector.close()


def test_connector_context_manager_exit_calls_client_close() -> None:
    client = FakeGitHubClient()
    closed: list[bool] = []
    client.close = lambda: closed.append(True)

    with GitHubConnector(config(), client=client) as connector:
        assert connector is not None

    assert closed == [True]


def test_config_without_owner_and_repo_raises() -> None:
    with pytest.raises(ValueError, match="owner/repo or repository_url"):
        GitHubRepositoryConfig()


@pytest.mark.parametrize("field_name", ["owner", "repo"])
def test_config_empty_owner_or_repo_raises(field_name: str) -> None:
    values = {"owner": "acme", "repo": "harbor-rag", field_name: ""}

    with pytest.raises(ValueError, match="owner/repo or repository_url"):
        GitHubRepositoryConfig(**values)


@pytest.mark.parametrize("value", UNSAFE_REPOSITORY_SEGMENTS)
@pytest.mark.parametrize("field_name", ["owner", "repo"])
def test_config_owner_or_repo_not_one_path_segment_raises(field_name: str, value: str) -> None:
    values = {"owner": "acme", "repo": "harbor-rag", field_name: value}

    with pytest.raises(ValueError, match=f"{field_name} must be one URL path segment"):
        GitHubRepositoryConfig(**values)


def test_config_invalid_owner_message_omits_value() -> None:
    with pytest.raises(ValueError, match="owner must be one URL path segment") as raised:
        GitHubRepositoryConfig(owner="acme corp/x", repo="harbor-rag")

    assert "acme corp" not in str(raised.value)


def test_config_repository_url_with_unsafe_repo_segment_raises() -> None:
    with pytest.raises(ValueError, match="repo must be one URL path segment"):
        GitHubRepositoryConfig(repository_url="https://github.com/acme/harbor%3Frag")


@pytest.mark.parametrize(
    ("owner", "repo"),
    [
        pytest.param("acme", "harbor-rag", id="hyphen"),
        pytest.param("o", "r", id="single-character"),
        pytest.param("user-other", "docs", id="user"),
        pytest.param("user_acme", "harbor.rag", id="managed-user-and-dotted-repo"),
    ],
)
def test_config_owner_and_repo_single_segments_are_kept(owner: str, repo: str) -> None:
    cfg = GitHubRepositoryConfig(owner=owner, repo=repo)

    assert (cfg.owner, cfg.repo) == (owner, repo)


def test_config_ref_and_branch_together_raises() -> None:
    with pytest.raises(ValueError, match="ref or branch, not both"):
        GitHubRepositoryConfig(owner="acme", repo="harbor-rag", ref="v1", branch="main")


def test_config_commit_sha_with_ref_raises() -> None:
    with pytest.raises(ValueError, match="commit_sha or ref/branch, not both"):
        GitHubRepositoryConfig(owner="acme", repo="harbor-rag", commit_sha="abc123", ref="v1")


def test_config_requests_per_minute_out_of_range_raises() -> None:
    with pytest.raises(ValueError, match="requests_per_minute must be between"):
        GitHubRepositoryConfig(owner="acme", repo="harbor-rag", requests_per_minute=0)


def test_config_non_https_api_url_raises() -> None:
    with pytest.raises(ValueError, match="api_url must be an HTTPS URL"):
        GitHubRepositoryConfig(
            owner="acme", repo="harbor-rag", api_url="http://ghe.internal/api/v3"
        )


def test_config_non_https_web_url_raises() -> None:
    with pytest.raises(ValueError, match="web_url must be an HTTPS URL"):
        GitHubRepositoryConfig(owner="acme", repo="harbor-rag", web_url="http://ghe.internal")
