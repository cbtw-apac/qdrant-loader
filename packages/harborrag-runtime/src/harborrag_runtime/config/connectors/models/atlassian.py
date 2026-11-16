"""Jira and Confluence source types.

Both authenticate the same way: a Cloud API token with the account email, or a
Data Center personal access token. ``api_token`` feeds the dataclass ``token``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import Field

from harborrag_adapters.connectors.atlassian.query import is_cloud_hostname
from harborrag_adapters.connectors.jira.query import narrow_jql

from .common import PagedHttpTuning
from .fields import Email, HttpsUrl, Secret, StrictModel, widget
from .spec import AuthMethodSpec, Capabilities, Setup, SourceTypeSpec

DeploymentType = Literal["cloud", "datacenter"]
ContentType = Literal["page", "blogpost"]

_BASE_URL_HELP = "Root URL of the site, without a trailing path"
_TOKEN_HELP = "Create one at id.atlassian.com › Security › API tokens"
_PAT_HELP = "Create one in your profile › Personal access tokens"
_DEPLOYMENT_HELP = "cloud or datacenter; inferred from the host name when unset"
_ALLOWED_HELP = (
    "Attachment file types to keep, such as pdf; left out, common document and image "
    "types; [] keeps every type"
)
_SIZE_HELP = "Largest attachment to read, in bytes; left out, 20 MiB"
_EXCLUDED_HELP = "Attachment file types to drop; wins over allowed_extensions"


class AtlassianCloudCredentials(StrictModel):
    """API token authentication for Atlassian Cloud."""

    base_url: HttpsUrl = Field(description=_BASE_URL_HELP, examples=["https://acme.atlassian.net"])
    email: Email = Field(description="Account the token belongs to", examples=["bot@acme.com"])
    api_token: Secret = Field(description=_TOKEN_HELP, examples=["ATATT3x…"])
    deployment_type: DeploymentType | None = Field(default=None, description=_DEPLOYMENT_HELP)


class AtlassianDataCenterCredentials(StrictModel):
    """Personal access token authentication for Data Center."""

    base_url: HttpsUrl = Field(description=_BASE_URL_HELP, examples=["https://jira.acme.internal"])
    api_token: Secret = Field(description=_PAT_HELP, examples=["NjM0…"])
    deployment_type: DeploymentType | None = Field(default=None, description=_DEPLOYMENT_HELP)


class AtlassianTuning(PagedHttpTuning):
    """Request settings of Jira and Confluence, whose REST APIs return at most 100 items a page."""

    page_size: int | None = Field(
        default=None, ge=1, le=100, description="Items to ask for per page, at most 100"
    )


class JiraConfig(StrictModel):
    """What to sync from Jira."""

    jql: str | None = Field(
        default=None,
        description="Extra JQL that narrows the issues to sync",
        examples=["project = CPM"],
        json_schema_extra=widget("textarea"),
    )
    project_keys: list[str] = Field(
        default_factory=list, description="Project keys to sync; empty syncs every project"
    )
    issue_types: list[str] = Field(
        default_factory=list, description="Issue types to keep; empty keeps every type"
    )
    statuses: list[str] = Field(
        default_factory=list, description="Statuses to keep; empty keeps every status"
    )
    labels: list[str] = Field(
        default_factory=list, description="Labels to keep; empty keeps every issue"
    )
    include_comments: bool = Field(default=True, description="Index issue comments")
    include_attachments: bool = Field(default=False, description="Download and parse attachments")
    include_changelog: bool = Field(default=False, description="Index the issue changelog")
    include_attachment_text_in_content: bool = Field(
        default=True, description="Inline parsed attachment text in the issue document"
    )
    include_all_fields: bool = Field(default=True, description="Fetch every issue field")
    fields: list[str] | None = Field(
        default=None, description="Issue fields to fetch when include_all_fields is false"
    )
    max_attachment_size_bytes: int | None = Field(default=None, ge=0, description=_SIZE_HELP)
    allowed_extensions: list[str] = Field(default_factory=list, description=_ALLOWED_HELP)
    excluded_extensions: list[str] = Field(default_factory=list, description=_EXCLUDED_HELP)
    max_comments: int | None = Field(
        default=None, ge=0, description="Most comments to index per issue; left out, all"
    )
    max_attachments: int | None = Field(
        default=None, ge=0, description="Most attachments to read per issue; left out, all"
    )
    max_changelog_items: int | None = Field(
        default=None, ge=0, description="Most changelog entries to index per issue; left out, all"
    )
    fail_on_error: bool = Field(default=False, description="Stop the run on the first item error")


class ConfluenceConfig(StrictModel):
    """What to sync from Confluence."""

    space_key: str = Field(min_length=1, description="Space to sync", examples=["ENG"])
    content_types: list[ContentType] = Field(
        default_factory=lambda: list[ContentType](["page"]),
        description="Content to sync: page, blogpost or both",
    )
    include_labels: list[str] = Field(default_factory=list, description="Keep pages with a label")
    exclude_labels: list[str] = Field(default_factory=list, description="Drop pages with a label")
    include_comments: bool = Field(default=False, description="Index page comments")
    include_attachments: bool = Field(default=False, description="Download and parse attachments")
    max_attachment_size_bytes: int | None = Field(default=None, ge=0, description=_SIZE_HELP)
    allowed_extensions: list[str] = Field(default_factory=list, description=_ALLOWED_HELP)
    excluded_extensions: list[str] = Field(default_factory=list, description=_EXCLUDED_HELP)
    max_comments: int | None = Field(
        default=None, ge=0, description="Most comments to index per page; left out, all"
    )
    max_attachments: int | None = Field(
        default=None, ge=0, description="Most attachments to read per page; left out, all"
    )
    fail_on_error: bool = Field(default=False, description="Stop the run on the first item error")


def _is_cloud(flat: Mapping[str, Any]) -> bool:
    """True for a Cloud site: named by ``deployment_type`` or, when unset, by its host."""
    deployment = str(flat.get("deployment_type") or "").strip().lower()
    if deployment:
        return deployment == "cloud"
    return is_cloud_hostname(str(flat.get("base_url") or ""))


def _auth_methods() -> tuple[AuthMethodSpec, ...]:
    """Return the auth methods Jira and Confluence share."""
    return (
        AuthMethodSpec("api_token", "API token", AtlassianCloudCredentials, implied_by=_is_cloud),
        AuthMethodSpec("pat", "Personal access token", AtlassianDataCenterCredentials),
    )


def _setups(product: str, cloud_url: str, datacenter_url: str) -> tuple[Setup, ...]:
    """Return the Cloud and Data Center setups of an Atlassian product."""
    return (
        Setup(
            "cloud",
            f"{product} Cloud",
            "api_token",
            "Sign in with the account email and an API token from id.atlassian.com",
            credentials={"base_url": cloud_url, "deployment_type": "cloud"},
        ),
        Setup(
            "datacenter",
            f"{product} Data Center",
            "pat",
            "Sign in with a personal access token from your profile",
            credentials={"base_url": datacenter_url, "deployment_type": "datacenter"},
        ),
    )


JIRA = SourceTypeSpec(
    source_type="jira",
    name="Jira",
    category="issue_tracker",
    provider="jira",
    auth_methods=_auth_methods(),
    config_model=JiraConfig,
    tuning_model=AtlassianTuning,
    capabilities=Capabilities(incremental=True, attachments=True),
    credential_renames={"api_token": "token"},
    endpoints=frozenset({"base_url"}),
    query_fields=frozenset({"jql"}),
    query_narrowers={"jql": narrow_jql},
    aliases=("jira_cloud", "jira_datacenter"),
    setups=_setups("Jira", "https://acme.atlassian.net", "https://jira.acme.internal"),
)

CONFLUENCE = SourceTypeSpec(
    source_type="confluence",
    name="Confluence",
    category="wiki",
    provider="confluence",
    auth_methods=_auth_methods(),
    config_model=ConfluenceConfig,
    tuning_model=AtlassianTuning,
    capabilities=Capabilities(incremental=True, attachments=True),
    credential_renames={"api_token": "token"},
    endpoints=frozenset({"base_url"}),
    aliases=("confluence_cloud", "confluence_datacenter"),
    setups=_setups(
        "Confluence", "https://acme.atlassian.net/wiki", "https://confluence.acme.internal"
    ),
)
