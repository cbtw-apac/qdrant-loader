"""SharePoint modern site page listing, fetching and HTML rendering.

Lists and fetches a site's modern pages through Graph and renders their text
web parts as one HTML document. A page ID reaches a Graph URL only through
``validate_graph_id_segment``, so an ID from a stored record stays inside one
URL path segment. Rendering is pure: it escapes the title and passes text web
part HTML through as Graph returns it.

Start from: SharePointPagesAPI, render_page_html.
"""

from __future__ import annotations

from collections.abc import Iterator
from html import escape
from typing import Any

from harborrag_adapters.connectors.exceptions import FetchError
from harborrag_adapters.connectors.schemas import ConnectorQuery
from harborrag_core.domain.source import SourceRecord

from .client import SharePointClient
from .config import SharePointSiteConfig
from .drive_paths import matches_pattern, validate_graph_id_segment
from .mappers import build_page_source_record, parse_timestamp

_MAX_PROVIDER_PAGES = 10_000
_TEXT_WEB_PART_TYPE = "#microsoft.graph.textWebPart"
_SITE_PAGE_ID_LABEL = "SharePoint site page ID"

PAGE_SELECT = ",".join(
    (
        "id",
        "name",
        "title",
        "webUrl",
        "pageLayout",
        "publishingState",
        "createdDateTime",
        "lastModifiedDateTime",
        "createdBy",
        "lastModifiedBy",
        "eTag",
    )
)


class SharePointPagesAPI:
    """SharePoint modern site page listing and canvas fetching for one connector config.

    Args:
        client: Graph client that sends the requests.
        config: Validated connector config; ``page_size`` sets the listing page size.
    """

    def __init__(self, client: SharePointClient, config: SharePointSiteConfig) -> None:
        self.client = client
        self.config = config

    def walk_pages(
        self,
        *,
        site: dict[str, Any],
        query: ConnectorQuery,
    ) -> Iterator[SourceRecord]:
        """Yield one source record per site page that passes query filters."""
        site_id = str(site["id"])
        for page in self.iter_pages(site_id):
            if self.should_process_page(page, query):
                yield build_page_source_record(page, site_id=site_id)

    def iter_pages(self, site_id: str) -> Iterator[dict[str, Any]]:
        """Iterate Graph sitePage collection pages for a site.

        Graph request errors pass through.

        Args:
            site_id: Graph site ID.

        Yields:
            dict[str, Any]: Each site page payload, page by page.

        Raises:
            FetchError: A page link repeats, the page cap is reached, or a page
                holds an invalid ``value`` list.
        """
        endpoint = f"sites/{site_id}/pages/microsoft.graph.sitePage"
        params: dict[str, Any] | None = {
            "$top": self.config.page_size,
            "$select": PAGE_SELECT,
        }
        seen_endpoints: set[str] = set()

        while endpoint:
            if endpoint in seen_endpoints or len(seen_endpoints) >= _MAX_PROVIDER_PAGES:
                raise FetchError("SharePoint pages pagination did not advance")
            seen_endpoints.add(endpoint)
            response = self.client.get_json(endpoint, params=params)
            raw_pages = response.get("value", [])
            if not isinstance(raw_pages, list) or any(
                not isinstance(page, dict) for page in raw_pages
            ):
                raise FetchError("SharePoint pages response contained an invalid value list")
            yield from raw_pages
            next_link = response.get("@odata.nextLink")
            endpoint = str(next_link) if next_link else ""
            params = None

    def get_page(self, site_id: str, page_id: str) -> dict[str, Any]:
        """Fetch one site page with its canvas layout expanded.

        The ``ValueError`` from ``validate_graph_id_segment`` is raised for an
        unsafe ``page_id`` before any request; Graph request errors pass through.

        Args:
            site_id: Graph site ID of the configured site.
            page_id: Site page ID, usually a GUID, from discovery or a stored record.

        Returns:
            The site page payload with ``canvasLayout``.
        """
        segment = validate_graph_id_segment(page_id, label=_SITE_PAGE_ID_LABEL)
        return self.client.get_json(
            f"sites/{site_id}/pages/{segment}/microsoft.graph.sitePage",
            params={"$expand": "canvasLayout"},
        )

    @staticmethod
    def should_process_page(page: dict[str, Any], query: ConnectorQuery) -> bool:
        """Apply query filters that make sense for a page (no size or extension)."""
        if not page.get("id"):
            return False
        if query.updated_after:
            updated_at = parse_timestamp(page.get("lastModifiedDateTime"))
            if updated_at and updated_at <= query.updated_after:
                return False
        return matches_pattern(page, query.pattern)


def page_title(page: dict[str, Any]) -> str:
    """Return the display title of a site page, falling back to its file name."""
    return str(page.get("title") or page.get("name") or page.get("id") or "")


def text_web_part_html(page: dict[str, Any]) -> list[str]:
    """Return text web part HTML in page reading order.

    Horizontal sections are read top to bottom, columns left to right, and web
    parts in each column top to bottom. The optional vertical section sits
    beside the page body, so it is read last. Every other web part type
    (images, lists, news, quick links) is skipped.
    """
    layout = page.get("canvasLayout")
    if not isinstance(layout, dict):
        return []
    web_parts: list[dict[str, Any]] = []
    for section in _dict_list(layout.get("horizontalSections")):
        for column in _dict_list(section.get("columns")):
            web_parts.extend(_dict_list(column.get("webparts")))
    vertical = layout.get("verticalSection")
    if isinstance(vertical, dict):
        web_parts.extend(_dict_list(vertical.get("webparts")))

    fragments = []
    for web_part in web_parts:
        if web_part.get("@odata.type") != _TEXT_WEB_PART_TYPE:
            continue
        inner_html = web_part.get("innerHtml")
        if isinstance(inner_html, str) and inner_html.strip():
            fragments.append(inner_html.strip())
    return fragments


def render_page_html(page: dict[str, Any]) -> tuple[str, bool]:
    """Build one HTML document for a page and report whether it had any text."""
    fragments = text_web_part_html(page)
    parts = [f"<h1>{escape(page_title(page))}</h1>", *fragments]
    return "\n".join(parts), bool(fragments)


def _dict_list(value: object) -> list[dict[str, Any]]:
    """Return the ``dict`` entries of a Graph list field; anything else gives ``[]``."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
