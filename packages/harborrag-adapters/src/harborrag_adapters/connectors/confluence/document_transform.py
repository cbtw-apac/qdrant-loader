"""Confluence-owned canonical document transformation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from html.parser import HTMLParser

from harborrag_core.domain import (
    Document,
    DocumentElement,
    DocumentRelation,
    ParsedDocument,
    RawDocument,
)

from .normalization import ConfluencePageNormalizer


class ConfluenceDocumentTransform:
    """Preserve page structure and synchronize comments as content units."""

    def __init__(self, pages: ConfluencePageNormalizer | None = None) -> None:
        self._pages = pages or ConfluencePageNormalizer()

    def transform(
        self,
        raw: RawDocument,
        parsed: ParsedDocument,
        document: Document,
    ) -> Document:
        del parsed
        if not isinstance(raw.raw, Mapping):
            raise ValueError("Confluence canonical normalization requires the source payload")
        canonical = self._pages.normalize_payload(
            raw.raw,
            source_url=raw.source,
            default_space_key=str(raw.metadata.get("space_key") or ""),
        )
        comments = self._comment_elements(raw.metadata.get("comments"))
        provenance = replace(
            canonical.provenance,
            author=document.provenance.author,
            checksum=document.provenance.checksum,
            created_at=document.provenance.created_at,
            updated_at=document.provenance.updated_at,
            tags=document.provenance.tags,
            extra={
                **document.provenance.extra,
                **canonical.provenance.extra,
            },
        )
        return replace(
            canonical,
            content=[
                *canonical.content,
                *(
                    [
                        DocumentElement(
                            id=f"{raw.id}#comments",
                            type="heading",
                            content="Comments",
                            metadata={"level": 1},
                        )
                    ]
                    if comments
                    else []
                ),
                *comments,
            ],
            provenance=provenance,
            relations=self._merge_relations(
                self._drop_superseded_attachment_refs(
                    canonical.relations,
                    document.relations,
                ),
                document.relations,
            ),
        )

    @classmethod
    def _comment_elements(cls, value: object) -> list[DocumentElement]:
        if not isinstance(value, (list, tuple)):
            return []
        elements: list[DocumentElement] = []
        for item in value:
            if not isinstance(item, Mapping):
                continue
            comment_id = str(item.get("id") or "").strip()
            body = cls._visible_text(str(item.get("body") or ""))
            if not comment_id or not body:
                continue
            metadata = {
                "role": "confluence.comment",
                "comment_id": comment_id,
                "comment_kind": str(item.get("comment_kind") or "PAGE_COMMENT"),
            }
            for key in (
                "author",
                "created_at",
                "updated_at",
                "parent_comment_id",
                "status",
            ):
                item_value = item.get(key)
                if item_value is not None and str(item_value).strip():
                    metadata[key] = str(item_value)
            elements.append(
                DocumentElement(
                    id=f"confluence-comment:{comment_id}",
                    type="paragraph",
                    content=body,
                    metadata=metadata,
                )
            )
        return elements

    @staticmethod
    def _visible_text(value: str) -> str:
        parser = _VisibleTextParser()
        parser.feed(value)
        parser.close()
        return " ".join("".join(parser.fragments).split())

    @staticmethod
    def _drop_superseded_attachment_refs(
        canonical: list[DocumentRelation],
        prior: list[DocumentRelation],
    ) -> list[DocumentRelation]:
        """Drop each body attachment reference whose file the connector already lists.

        A body media node names its file by UUID (``media_id``), while the connector's
        attachment list names the same file by its v1 id. The listed attachment's ``file_id``
        is the bridge. A reference is dropped only when its ``media_id`` matches a listed
        file; any other reference, including one to an attachment outside the list (another
        page's file, a truncated or skipped one), is kept.
        """

        listed = {
            str(relation.metadata.get("file_id") or "").casefold()
            for relation in prior
            if relation.predicate == "has_attachment"
        }
        listed.discard("")
        if not listed:
            return canonical
        return [
            relation
            for relation in canonical
            if not (
                relation.predicate == "has_attachment"
                and relation.target_type == "attachment"
                and str(relation.metadata.get("media_id") or "").casefold() in listed
            )
        ]

    @staticmethod
    def _merge_relations(*groups: list[DocumentRelation]) -> list[DocumentRelation]:
        relations: dict[tuple[str, str, str], DocumentRelation] = {}
        for relation in (relation for group in groups for relation in group):
            key = (
                relation.predicate,
                relation.target_id,
                relation.target_type,
            )
            relations.setdefault(key, relation)
        return list(relations.values())


class _VisibleTextParser(HTMLParser):
    _BLOCK_TAGS = frozenset(
        {
            "blockquote",
            "br",
            "div",
            "li",
            "ol",
            "p",
            "pre",
            "table",
            "td",
            "th",
            "tr",
            "ul",
        }
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fragments: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del attrs
        if tag in self._BLOCK_TAGS:
            self.fragments.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._BLOCK_TAGS:
            self.fragments.append(" ")

    def handle_data(self, data: str) -> None:
        if data:
            self.fragments.append(data)
