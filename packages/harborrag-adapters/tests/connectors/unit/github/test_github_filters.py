"""Unit tests for GitHub connector query/config-based file filtering."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from github_test_helpers import commit, config, tree_item

from harborrag_adapters.connectors import GitHubRepositoryConfig
from harborrag_adapters.connectors.github import filters as github_filters
from harborrag_adapters.connectors.schemas import ConnectorQuery

pytestmark = [pytest.mark.unit, pytest.mark.whitebox]


def _query(**overrides: Any) -> ConnectorQuery:
    return ConnectorQuery(**overrides)


def _processed(cfg: GitHubRepositoryConfig, path: str, query: ConnectorQuery) -> bool:
    item = tree_item(path, "sha-file")
    return github_filters.should_process_file(cfg, item, query, commit=commit())


def _reject(path: str, size: int, mime: str) -> tuple[bool, str]:
    return False, "not needed"


def _allow(path: str, size: int, mime: str) -> tuple[bool, str]:
    return True, ""


def _explode(path: str, size: int, mime: str) -> tuple[bool, str]:
    raise RuntimeError("callback failed")


def test_should_process_file_commit_older_than_updated_after_returns_false() -> None:
    query = _query(updated_after=datetime(2099, 1, 1, tzinfo=UTC))

    assert not _processed(config(), "src/app.py", query)


def test_should_process_file_commit_newer_than_updated_after_returns_true() -> None:
    query = _query(updated_after=datetime(2000, 1, 1, tzinfo=UTC))

    assert _processed(config(), "src/app.py", query)


def test_should_process_file_configured_excluded_extension_returns_false() -> None:
    cfg = config(excluded_extensions={".png"})

    assert not _processed(cfg, "assets/logo.png", _query())


def test_should_process_file_outside_configured_include_paths_returns_false() -> None:
    cfg = config(include_paths=["src"])

    assert not _processed(cfg, "docs/readme.md", _query())


def test_should_process_file_under_configured_exclude_paths_returns_false() -> None:
    cfg = config(exclude_paths=["tests"])

    assert not _processed(cfg, "tests/test_app.py", _query())


def test_should_process_file_no_configured_include_glob_match_returns_false() -> None:
    cfg = config(include_globs=["*.py"])

    assert not _processed(cfg, "README.md", _query())


def test_should_process_file_configured_exclude_glob_match_returns_false() -> None:
    cfg = config(exclude_globs=["*.md"])

    assert not _processed(cfg, "README.md", _query())


def test_should_process_file_oversized_file_returns_false() -> None:
    cfg = config(max_file_size_bytes=5)
    item = tree_item("big.txt", "sha-big", size=50)

    assert not github_filters.should_process_file(cfg, item, _query(), commit=commit())


def test_should_process_file_callback_rejects_returns_false() -> None:
    calls: list[str] = []

    def reject(path: str, size: int, mime: str) -> tuple[bool, str]:
        calls.append(path)
        return _reject(path, size, mime)

    cfg = config(process_file_callback=reject)

    assert not _processed(cfg, "src/app.py", _query())
    assert calls == ["src/app.py"]


def test_should_process_file_callback_accepts_returns_true() -> None:
    cfg = config(process_file_callback=_allow)

    assert _processed(cfg, "src/app.py", _query())


def test_should_process_file_callback_error_without_fail_on_error_returns_false() -> None:
    cfg = config(process_file_callback=_explode, fail_on_error=False)

    assert not _processed(cfg, "src/app.py", _query())


def test_should_process_file_callback_error_with_fail_on_error_raises() -> None:
    cfg = config(process_file_callback=_explode, fail_on_error=True)

    with pytest.raises(RuntimeError):
        _processed(cfg, "src/app.py", _query())


def test_should_process_file_caller_extensions_string_alias_narrows_selection() -> None:
    query = _query(filters={"extensions": "PY"})

    assert _processed(config(), "src/app.py", query)
    assert not _processed(config(), "README.md", query)


def test_should_process_file_caller_allowed_extensions_list_normalizes_values() -> None:
    query = _query(filters={"allowed_extensions": [".PY", "md"]})

    assert _processed(config(), "src/app.py", query)
    assert _processed(config(), "README.md", query)
    assert not _processed(config(), "assets/logo.png", query)


def test_should_process_file_caller_excluded_extensions_string_lowercases_value() -> None:
    query = _query(filters={"excluded_extensions": ".PNG"})

    assert not _processed(config(), "assets/logo.png", query)
    assert _processed(config(), "src/app.py", query)


def test_should_process_file_caller_include_paths_string_narrows_selection() -> None:
    query = _query(filters={"include_paths": "src"})

    assert _processed(config(), "src/app.py", query)
    assert not _processed(config(), "docs/readme.md", query)


def test_should_process_file_caller_include_paths_list_includes_each_path() -> None:
    query = _query(filters={"include_paths": ["src", "docs"]})

    assert _processed(config(), "src/app.py", query)
    assert _processed(config(), "docs/readme.md", query)
    assert not _processed(config(), "tests/test_app.py", query)


@pytest.mark.parametrize(
    ("configured", "requested", "path"),
    [
        pytest.param(
            {"include_paths": ["src"]},
            {"include_paths": []},
            "docs/readme.md",
            id="empty-include-paths",
        ),
        pytest.param(
            {"include_paths": ["src"]},
            {"include_paths": ["docs"]},
            "docs/readme.md",
            id="other-include-paths",
        ),
        pytest.param(
            {"exclude_paths": ["tests"]},
            {"exclude_paths": []},
            "tests/test_app.py",
            id="empty-exclude-paths",
        ),
        pytest.param(
            {"exclude_paths": ["tests"]},
            {"exclude_paths": ["docs"]},
            "tests/test_app.py",
            id="other-exclude-paths",
        ),
        pytest.param(
            {"allowed_extensions": {".py"}},
            {"allowed_extensions": []},
            "README.md",
            id="empty-allowed-extensions",
        ),
        pytest.param(
            {"allowed_extensions": {".py"}},
            {"extensions": ["md"]},
            "README.md",
            id="other-extensions-alias",
        ),
        pytest.param(
            {"excluded_extensions": {".png"}},
            {"excluded_extensions": []},
            "assets/logo.png",
            id="empty-excluded-extensions",
        ),
        pytest.param(
            {"include_globs": ["*.py"]},
            {"include_globs": []},
            "README.md",
            id="empty-include-globs",
        ),
        pytest.param(
            {"include_globs": ["*.py"]},
            {"include_globs": ["*.md"]},
            "README.md",
            id="other-include-globs",
        ),
        pytest.param(
            {"exclude_globs": ["*.md"]},
            {"exclude_globs": []},
            "README.md",
            id="empty-exclude-globs",
        ),
    ],
)
def test_should_process_file_caller_filter_outside_configured_filter_returns_false(
    configured: dict[str, Any],
    requested: dict[str, Any],
    path: str,
) -> None:
    assert not _processed(config(**configured), path, _query(filters=requested))


def test_should_process_file_caller_include_paths_inside_configured_narrow_selection() -> None:
    cfg = config(include_paths=["src"])
    query = _query(filters={"include_paths": ["src/pkg"]})

    assert _processed(cfg, "src/pkg/app.py", query)
    assert not _processed(cfg, "src/app.py", query)


def test_should_process_file_caller_extensions_inside_configured_narrow_selection() -> None:
    cfg = config(allowed_extensions={".py", ".md"})
    query = _query(filters={"allowed_extensions": [".py", ".png"]})

    assert _processed(cfg, "src/app.py", query)
    assert not _processed(cfg, "README.md", query)
    assert not _processed(cfg, "assets/logo.png", query)


def test_should_process_file_caller_exclude_paths_add_to_configured_exclusions() -> None:
    cfg = config(exclude_paths=["tests"])
    query = _query(filters={"exclude_paths": ["docs"]})

    assert not _processed(cfg, "docs/readme.md", query)
    assert not _processed(cfg, "tests/test_app.py", query)
    assert _processed(cfg, "src/app.py", query)


@pytest.mark.parametrize(
    "requested",
    [
        pytest.param({"include_paths": ["src", "../outside"]}, id="include-paths"),
        pytest.param({"exclude_paths": ["docs", "../outside"]}, id="exclude-paths"),
        pytest.param({"include_globs": ["*.py", "../outside"]}, id="include-globs"),
        pytest.param({"exclude_globs": ["*.md", "../outside"]}, id="exclude-globs"),
    ],
)
def test_should_process_file_caller_filter_parent_segment_after_a_match_raises(
    requested: dict[str, Any],
) -> None:
    """An entry that matches first must not hide a later ``..`` entry from validation."""
    with pytest.raises(ValueError, match=r"must not contain '\.\.' segments"):
        _processed(config(), "src/app.py", _query(filters=requested))


def test_file_paths_from_query_string_alias_returns_one_path() -> None:
    query = _query(filters={"paths": "src/App.PY"})

    assert github_filters.file_paths_from_query(query) == ["src/App.PY"]


def test_file_paths_from_query_absent_returns_empty() -> None:
    assert github_filters.file_paths_from_query(_query()) == []


def test_file_paths_from_query_parent_segment_raises_value_error() -> None:
    query = _query(filters={"file_paths": ["../../other-repo/contents/x"]})

    with pytest.raises(ValueError, match=r"must not contain '\.\.' segments"):
        github_filters.file_paths_from_query(query)
