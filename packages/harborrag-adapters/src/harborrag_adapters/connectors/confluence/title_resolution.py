"""Resolution of Confluence ``ac:link`` page titles to page ids.

Lookups stay inside the connection's configured space: a link that names another
space is left unresolved without a search, so page content cannot be used to
probe which titles exist elsewhere. A failed lookup degrades to unresolved and
never fails the document.

Start from: PageTitleResolver.page_id_for_title.
"""

from __future__ import annotations

import logging
from hashlib import sha256

from .content import ConfluenceContentAPI
from .query import quote_cql

logger = logging.getLogger("harborrag.adapters.connectors.confluence")


def _title_digest(title: str) -> str:
    """Reduce a page title to a stable, non-reversible handle for logs.

    A title is document content, not an identifier: on a customer space it carries
    customer names, incident numbers and unreleased product names, and these two lines
    fire once per unresolved title on every run. The digest is stable across runs, so an
    operator can still count occurrences and correlate them with a CQL search of their
    own, without the space's vocabulary being copied into log storage.
    """
    return sha256(title.encode("utf-8")).hexdigest()[:12]


class PageTitleResolver:
    """Turn a page title into the page id the graph keys that page by.

    Confluence writes in-body link targets by title far more often than by id: measured on
    a live space, 173 of 173 ``ri:page`` references carried ``ri:content-title`` and none
    carried ``ri:content-id``. A title is not an identity -- the graph keys pages by
    ``page_id``, so emitting a title-keyed target would mint a second node that can never
    converge with the real page -- which is why the title has to become an id here or not
    become an edge at all.

    One request per distinct title per connector instance, negatives cached too: a title
    that belongs to another space costs one lookup for the run rather than one per
    occurrence. Only a *completed* search is cached -- see ``page_id_for_title``.

    Args:
        content: Content API of the connection; its config names the space that
            lookups stay inside.
    """

    def __init__(self, content: ConfluenceContentAPI) -> None:
        self._content = content
        self._page_ids: dict[tuple[str, str], str | None] = {}

    def page_id_for_title(self, space_key: str, title: str) -> str | None:
        """Resolve one title, or return None when it cannot be resolved.

        A title in a space other than the configured one is never looked up and
        stays unresolved.

        A lookup failure never fails the document. The body still parses and the link is
        simply unresolved -- the same state every one of these links was in before titles
        were read at all -- so a rate limit or a revoked token degrades the graph rather
        than failing ingestion.

        A failed request is not a completed search, so it is never cached. Caching it
        would let one 429 or one dropped connection pin every later reference to that
        title as unresolved for the lifetime of the connector; a completed search that
        found nothing is a real answer and is cached as one.

        Args:
            space_key: Space the link names; the configured space when the link names none.
            title: Page title the link targets.

        Returns:
            The page id, or None when the title is in another space, not found or
            could not be looked up.
        """
        if space_key != self._content.config.space_key:
            logger.debug(
                "Confluence link title targets another space space=%s title_digest=%s",
                space_key,
                _title_digest(title),
            )
            return None
        cache_key = (space_key, title)
        if cache_key in self._page_ids:
            return self._page_ids[cache_key]
        try:
            resolved = self._lookup(space_key, title)
        except Exception as error:  # noqa: BLE001 - degrade to unresolved, never fail load
            logger.warning(
                "Confluence link title lookup failed space=%s title_digest=%s error_type=%s",
                space_key,
                _title_digest(title),
                type(error).__name__,
            )
            return None
        if resolved is None:
            logger.info(
                "Confluence link title did not resolve to a page space=%s title_digest=%s",
                space_key,
                _title_digest(title),
            )
        self._page_ids[cache_key] = resolved
        return resolved

    def _lookup(self, space_key: str, title: str) -> str | None:
        """Search one space for a page with this exact title and return its id.

        ``type = page`` keeps a same-titled attachment, comment or blog post out of the
        result set. An unconstrained CQL search returns every content type, the first
        numeric id wins here, and every one of those types carries a numeric id, so
        without the constraint a relation could be keyed to the wrong source item.
        """
        cql = f"space = {quote_cql(space_key)} and title = {quote_cql(title)} and type = page"
        for content in self._content.search(cql):
            candidate = str(content.get("id") or "")
            if candidate.isdigit():
                return candidate
        return None
