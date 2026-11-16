"""Unit tests for SharePoint connector configuration validation."""

from __future__ import annotations

import pytest
from sharepoint_test_helpers import SITE_URL, config

from harborrag_adapters.connectors import SharePointSiteConfig
from harborrag_adapters.connectors.sharepoint.drive_paths import parse_sharepoint_site_url

pytestmark = [pytest.mark.unit, pytest.mark.graybox]

_HOSTNAME = "contoso.sharepoint.com"
_GRAPH_SITE_ID = "contoso.sharepoint.com,4e2b1d3a-8c7f-4b6e-9a1d-2f3c4b5a6d7e,0f1e2d3c-4b5a-4978-8796-a5b4c3d2e1f0"
_LONG_HOSTNAME = ".".join(["a" * 50] * 6)

_VALID_SITE_LOCATIONS = [
    ("site_id", "site1"),
    ("site_id", "s1"),
    ("site_id", "other-site"),
    ("site_id", "site-123"),
    ("site_id", _GRAPH_SITE_ID),
    ("drive_id", "drive1"),
    ("drive_id", "drive2"),
    ("drive_id", "other-drive"),
    ("drive_id", "b!Xy-z_09AbCdEf"),
    ("hostname", _HOSTNAME),
    ("hostname", "ex.sharepoint.com"),
    ("hostname", "Contoso-EU.SharePoint.com"),
    ("site_path", ""),
    ("site_path", "sites/Engineering"),
    ("site_path", "/sites/knowledge"),
    ("site_path", "teams/HR Team"),
]

_UNSAFE_SITE_LOCATIONS = [
    ("site_id", "site1/../../sites/other-site"),
    ("site_id", f"{_GRAPH_SITE_ID}x/../../sites/other-site"),
    ("site_id", "."),
    ("site_id", ".."),
    ("site_id", "a/b"),
    ("site_id", "a?b"),
    ("site_id", "a#b"),
    ("site_id", "a%2Fb"),
    ("site_id", "a:b"),
    ("site_id", "a b"),
    ("drive_id", "../drive2"),
    ("drive_id", ".."),
    ("drive_id", "a/b"),
    ("drive_id", "a?b"),
    ("drive_id", "a#b"),
    ("drive_id", "a%2Fb"),
    ("drive_id", "a:b"),
    ("drive_id", "a.b"),
    ("hostname", "contoso.sharepoint.com/sites/other-site"),
    ("hostname", "contoso.sharepoint.com:443"),
    ("hostname", "a?b"),
    ("hostname", "a#b"),
    ("hostname", "a%2Fb"),
    ("hostname", ".."),
    ("hostname", "a..b"),
    ("hostname", "-contoso.sharepoint.com"),
    ("hostname", "contoso-.sharepoint.com"),
    ("hostname", "a_b.example.com"),
    ("hostname", f"{'a' * 64}.example.com"),
    ("hostname", _LONG_HOSTNAME),
    ("site_path", "sites/../other-site"),
    ("site_path", "sites/./x"),
    ("site_path", "sites//x"),
    ("site_path", "sites/a?b"),
    ("site_path", "sites/a#b"),
    ("site_path", "sites/a%2Fb"),
    ("site_path", "sites/a:b"),
    ("site_path", "sites\\x"),
    ("site_path", "sites/a\nb"),
]

_ECHO_PROBES = [
    ("site_id", "site1/../../sites/other-site"),
    ("drive_id", "../../sites/other-site/drive"),
    ("hostname", "other-site.example.com/x"),
    ("site_path", "sites/../other-site"),
]


def _site_config(field: str, value: str) -> SharePointSiteConfig:
    location = {"site_url": None, "hostname": _HOSTNAME, "site_path": "sites/Engineering"}
    return config(**{**location, field: value})


def test_config_site_url_and_extensions_parsed_and_normalized() -> None:
    cfg = config(allowed_extensions={"docx", ".PDF"}, excluded_extensions={"tmp"})

    assert cfg.hostname == "contoso.sharepoint.com"
    assert cfg.site_path == "sites/Engineering"
    assert cfg.allowed_extensions == {".docx", ".pdf"}
    assert cfg.excluded_extensions == {".tmp"}
    assert parse_sharepoint_site_url(SITE_URL) == (
        "contoso.sharepoint.com",
        "sites/Engineering",
    )


def test_config_without_site_raises() -> None:
    with pytest.raises(ValueError, match="requires either site_id or site_url"):
        SharePointSiteConfig(access_token="token")


def test_config_without_credentials_raises() -> None:
    with pytest.raises(ValueError, match="access_token or client credentials"):
        SharePointSiteConfig(site_url=SITE_URL)


def test_config_requests_per_minute_out_of_range_raises() -> None:
    with pytest.raises(ValueError, match="requests_per_minute must be between"):
        config(requests_per_minute=0)


def test_config_page_size_out_of_range_raises() -> None:
    with pytest.raises(ValueError, match="page_size must be between"):
        config(page_size=0)


@pytest.mark.parametrize(("field", "value"), _VALID_SITE_LOCATIONS)
def test_config_safe_site_location_keeps_value(field: str, value: str) -> None:
    assert getattr(_site_config(field, value), field) == value


def test_config_root_site_url_keeps_empty_site_path() -> None:
    cfg = config(site_url="https://contoso.sharepoint.com/")

    assert (cfg.hostname, cfg.site_path) == ("contoso.sharepoint.com", "")


@pytest.mark.parametrize(("field", "value"), _UNSAFE_SITE_LOCATIONS)
def test_config_unsafe_site_location_raises_naming_field(field: str, value: str) -> None:
    with pytest.raises(ValueError, match=rf"^{field} "):
        _site_config(field, value)


@pytest.mark.parametrize(("field", "value"), _ECHO_PROBES)
def test_config_unsafe_site_location_keeps_value_out_of_message(field: str, value: str) -> None:
    with pytest.raises(ValueError, match=rf"^{field} ") as error:
        _site_config(field, value)

    assert "other-site" not in str(error.value)


@pytest.mark.parametrize(
    ("site_url", "field"),
    [
        ("https://contoso.sharepoint.com/sites/x/../other-site", "site_path"),
        ("https://contoso.sharepoint.com/sites/%2e%2e/other-site", "site_path"),
        ("https://contoso.sharepoint.com/sites/a%3Fb", "site_path"),
        ("https://contoso.sharepoint.com/sites/a%23b", "site_path"),
        ("https://contoso.sharepoint.com/sites/a%3Ab", "site_path"),
        ("https://contoso.sharepoint.com/sites/a%252Fb", "site_path"),
        ("https://contoso.sharepoint.com%2F..%2Fother-site/sites/a", "hostname"),
    ],
)
def test_config_unsafe_site_url_raises_naming_parsed_field(site_url: str, field: str) -> None:
    with pytest.raises(ValueError, match=rf"^{field} "):
        config(site_url=site_url)
