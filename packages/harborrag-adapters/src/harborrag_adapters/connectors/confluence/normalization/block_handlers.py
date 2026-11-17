from __future__ import annotations

import abc
import re
from collections.abc import Mapping
from urllib.parse import urlsplit, urlunsplit

from harborrag_core.domain import (
    DocumentBlockKind,
    DocumentRelation,
    TableArtifact,
)

from .block_models import BlockContext, BlockDraft, BlockPresentation
from .include_handlers import ConfluenceIncludeTableHandlers
from .macros import ConfluenceMacroHandlerRegistry
from .nodes import ConfluenceNode
from .tables import TableArtifactBuilder

_PAGE_ID_PATTERN = re.compile(r"/pages/(\d+)(?:/|$)")
_BLOCK_KIND_BY_NODE = {
    "paragraph": DocumentBlockKind.PARAGRAPH,
    "list": DocumentBlockKind.LIST,
    "list_item": DocumentBlockKind.LIST_ITEM,
    "code_block": DocumentBlockKind.CODE_BLOCK,
    "quote": DocumentBlockKind.QUOTE,
    "panel": DocumentBlockKind.PANEL,
    "expand": DocumentBlockKind.EXPAND,
    # ADF's native tabs feature (tabsContainer/tabsPage in adf.py's
    # _KIND_MAP) reaches this generic dispatch directly, unlike the
    # storage-format tabs macro (tabs/tab-set/tab, handled via _append_macro
    # instead) -- both must resolve to the same DocumentBlockKind so
    # _container_context extends tab_path identically for either
    # representation.
    "tab_set": DocumentBlockKind.TAB_SET,
    "tab": DocumentBlockKind.TAB,
}
# Node kinds independently populated as their own block draft somewhere in
# `_append_node`'s dispatch (generic block kinds, tables, macros, and preserved
# unsupported nodes). A container's own `visible_text()` aggregate must exclude
# these kinds wherever it also independently populates them, or the same source
# text is emitted twice: once via the aggregate, once via the nested block.
_NESTED_BLOCK_KINDS = frozenset({*_BLOCK_KIND_BY_NODE, "table", "macro", "unsupported"})


class ConfluenceBlockHandlers(ConfluenceIncludeTableHandlers, abc.ABC):
    """Append non-heading nodes while the hierarchy builder owns section policy."""

    _document_id: str
    _space_key: str
    _macros: ConfluenceMacroHandlerRegistry
    _tables: TableArtifactBuilder
    _table_artifacts: list[TableArtifact]
    _warnings: list[str]
    _relations: list[DocumentRelation]
    _table_ordinal: int

    def _append_node(
        self,
        parent: BlockDraft,
        node: ConfluenceNode,
        context: BlockContext,
    ) -> None:
        if node.kind in {"group", "document", "text"}:
            self._append_group(parent, node, context)
            return
        if node.kind == "macro":
            self._append_macro(parent, node, context)
            return
        if node.kind == "table":
            self._append_table(parent, node, context)
            return
        if node.kind in {"link", "media"}:
            self._append_reference(parent, node, context)
            return
        if node.kind == "unsupported":
            self._append_unsupported(parent, node, context)
            return
        kind = _BLOCK_KIND_BY_NODE.get(node.kind)
        if kind is None:
            self._append_group(parent, node, context)
            return
        text = node.visible_text(exclude_kinds=_NESTED_BLOCK_KINDS)
        draft = self._draft(
            node,
            kind,
            parent,
            context,
            BlockPresentation(
                text=text or None,
                title=self._container_title(node, kind),
                attributes=self._node_attributes(node),
            ),
        )
        parent.children.append(draft)
        child_context = self._container_context(context, draft)
        child_nodes = tuple(
            child for child in node.children if child.kind not in {"text", "link", "media"}
        )
        if child_nodes:
            self._populate(draft, child_nodes, child_context)
        self._append_inline_references(draft, node, child_context)

    def _append_group(
        self,
        parent: BlockDraft,
        node: ConfluenceNode,
        context: BlockContext,
    ) -> None:
        if node.text.strip():
            paragraph = self._draft(
                node,
                DocumentBlockKind.PARAGRAPH,
                parent,
                context,
                BlockPresentation(text=node.text.strip()),
            )
            parent.children.append(paragraph)
        self._populate(parent, node.children, context)

    def _append_macro(
        self,
        parent: BlockDraft,
        node: ConfluenceNode,
        context: BlockContext,
    ) -> None:
        key = str(node.attributes.get("macro_name") or "unknown")
        parameters = node.attributes.get("parameters")
        handler = self._macros.resolve(key)
        handling = handler.handle(
            key,
            parameters if isinstance(parameters, Mapping) else {},
        )
        if handling.warning:
            self._warnings.append(handling.warning)
        include_target = self._include_target_attributes(node, key)
        include_title = include_target.get("target_title")
        draft = self._draft(
            node,
            handling.kind,
            parent,
            context,
            BlockPresentation(
                text=(
                    node.visible_text(exclude_kinds=_NESTED_BLOCK_KINDS)
                    or (str(include_title) if include_title else None)
                ),
                title=(str(include_title) if include_title else handling.title),
                attributes={
                    "macro_key": key,
                    "macro_id": str(node.attributes.get("macroId") or node.source_id),
                    "parameters": dict(handling.parameters),
                    "emits_container": handler.emits_container,
                    "emits_visible_content": handler.emits_visible_content,
                    "emits_table": handler.emits_table,
                    "needs_rendered_fallback": handler.needs_rendered_fallback,
                    **include_target,
                },
            ),
        )
        parent.children.append(draft)
        self._append_include_relation(node, key, include_target)
        child_context = self._container_context(context, draft)
        child_nodes = tuple(
            child for child in node.children if child.kind not in {"text", "link", "media"}
        )
        if child_nodes:
            self._populate(draft, child_nodes, child_context)
        self._append_inline_references(draft, node, child_context)

    def _append_reference(
        self,
        parent: BlockDraft,
        node: ConfluenceNode,
        context: BlockContext,
    ) -> None:
        kind = (
            DocumentBlockKind.LINK_REFERENCE
            if node.kind == "link"
            else DocumentBlockKind.MEDIA_REFERENCE
        )
        attributes = self._reference_attributes(node)
        parent.children.append(
            self._draft(
                node,
                kind,
                parent,
                context,
                BlockPresentation(
                    text=node.visible_text() or None,
                    attributes=attributes,
                ),
            )
        )
        target = attributes.get("target_page_id") or attributes.get("attachment_id")
        if isinstance(target, str) and target:
            self._relations.append(
                DocumentRelation(
                    predicate="links_to" if node.kind == "link" else "has_attachment",
                    target_id=target,
                    target_type="document" if node.kind == "link" else "attachment",
                    metadata={
                        "source_block_id": node.source_id,
                        # A media node names its file by UUID; the transform matches it to the
                        # listed attachment's fileId before dropping the body copy.
                        **({"media_id": target.casefold()} if node.kind == "media" else {}),
                    },
                )
            )

    def _append_unsupported(
        self,
        parent: BlockDraft,
        node: ConfluenceNode,
        context: BlockContext,
    ) -> None:
        self._warnings.append(f"unsupported Confluence block preserved: {node.kind}")
        draft = self._draft(
            node,
            DocumentBlockKind.UNSUPPORTED,
            parent,
            context,
            BlockPresentation(
                text=node.visible_text(exclude_kinds=_NESTED_BLOCK_KINDS) or None,
                attributes={"source_kind": node.kind},
            ),
        )
        parent.children.append(draft)
        child_context = self._container_context(context, draft)
        child_nodes = tuple(
            child for child in node.children if child.kind not in {"text", "link", "media"}
        )
        if child_nodes:
            self._populate(draft, child_nodes, child_context)
        self._append_inline_references(draft, node, child_context)

    def _append_inline_references(
        self,
        parent: BlockDraft,
        node: ConfluenceNode,
        context: BlockContext,
    ) -> None:
        """Create reference blocks for direct link/media children only.

        Other children are populated recursively through `_append_node`, including their
        nested references. Recursing here would emit those references twice under the
        wrong parent.
        """

        for child in node.children:
            if child.kind in {"link", "media"}:
                self._append_reference(parent, child, context)

    @staticmethod
    def _reference_attributes(node: ConfluenceNode) -> dict[str, object]:
        if node.kind == "media":
            return {
                "attachment_id": str(
                    node.attributes.get("attachment_id") or node.attributes.get("id") or ""
                ),
                "filename": str(
                    node.attributes.get("filename") or node.attributes.get("alt") or ""
                ),
                "media_type": str(node.attributes.get("type") or ""),
            }
        href = str(node.attributes.get("href") or "")
        safe_url = _safe_url(href)
        match = _PAGE_ID_PATTERN.search(urlsplit(safe_url).path)
        return {
            "anchor_text": node.visible_text(),
            "target_url": safe_url,
            "target_page_id": str(
                node.attributes.get("target_page_id") or (match.group(1) if match else "")
            ),
        }

    @staticmethod
    def _container_title(
        node: ConfluenceNode,
        kind: DocumentBlockKind,
    ) -> str | None:
        value = node.attributes.get("title")
        if value and str(value).strip():
            return str(value).strip()
        if kind == DocumentBlockKind.EXPAND:
            return "Details"
        return None

    @staticmethod
    def _node_attributes(node: ConfluenceNode) -> dict[str, object]:
        allowed = {"ordered", "panelType", "panel-type", "type", "icon"}
        return {
            str(key): value
            for key, value in node.attributes.items()
            if key in allowed and isinstance(value, (str, int, bool))
        }

    @abc.abstractmethod
    def _populate(
        self,
        parent: BlockDraft,
        nodes: tuple[ConfluenceNode, ...],
        base_context: BlockContext,
    ) -> None: ...

    @abc.abstractmethod
    def _draft(
        self,
        node: ConfluenceNode,
        kind: DocumentBlockKind,
        parent: BlockDraft,
        context: BlockContext,
        presentation: BlockPresentation,
    ) -> BlockDraft: ...

    @abc.abstractmethod
    def _container_context(
        self,
        context: BlockContext,
        draft: BlockDraft,
    ) -> BlockContext: ...


def _safe_url(value: str) -> str:
    if not value:
        return ""
    parsed = urlsplit(value)
    if parsed.scheme and parsed.scheme not in {"http", "https"}:
        return ""
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", parsed.fragment))
