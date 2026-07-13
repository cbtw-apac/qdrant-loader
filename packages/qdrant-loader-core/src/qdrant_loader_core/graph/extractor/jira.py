from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from qdrant_loader.core.document import Document

from qdrant_loader_core.graph.extractor.base_extractor import (
    BaseEntityExtractor,
)
from qdrant_loader_core.graph.models import (
    CoreEdgeType,
    CoreNodeLabel,
    GraphEdge,
    GraphNode,
    PersonInfo,
)


class JiraEntityExtractor(BaseEntityExtractor):
    """
    Jira graph extractor.

    Extracts:
    - Document node (status, priority, issue_type)
    - Person nodes (reporter, assignee)
    - Container node (jira project)
    - Label nodes
    - Linked issue relationships
    - Parent/subtask relationships
    - Cross-source links from URLs found in description
    """

    # NOTE:
    # `parent_key` covers both subtask-of-parent and story/task-of-epic relations
    # (Jira surfaces both through the same "parent" field); the PART_OF edge's
    # "kind" is derived from issue_type to distinguish the two.

    source_type = "jira"

    CONFLUENCE_URL_RE = re.compile(
        r"https?://[^\s]*confluence[^\s]+",
        re.IGNORECASE,
    )

    GIT_URL_RE = re.compile(
        r"https?://(?:github|gitlab|bitbucket)[^\s]+",
        re.IGNORECASE,
    )

    # ------------------------------------------------------------------
    # Project
    # ------------------------------------------------------------------

    def _project(
        self,
        doc: Document,
    ) -> str | None:
        return doc.metadata.get("project_key")

    # ------------------------------------------------------------------
    # Document
    # ------------------------------------------------------------------

    def _build_document_node(
        self,
        doc: Document,
        project: str | None,
    ) -> GraphNode:
        metadata = doc.metadata

        return GraphNode(
            id=metadata.get("key"),
            label=CoreNodeLabel.DOCUMENT.value,
            project=project,
            properties={
                "title": doc.title,
                "source_type": self.source_type,
                "status": metadata.get("status"),
                "priority": metadata.get("priority"),
                "issue_type": metadata.get("issue_type"),
            },
        )

    # ------------------------------------------------------------------
    # People
    # ------------------------------------------------------------------

    def _extract_people(
        self,
        doc: Document,
    ) -> list[tuple[PersonInfo, str]]:
        people = []

        reporter = doc.metadata.get("reporter")

        if reporter:
            if isinstance(reporter, dict):
                person_id = (
                    reporter.get("email_address")
                    or reporter.get("account_id")
                    or reporter.get("display_name")
                )
                display_name = reporter.get("display_name", person_id)
            else:
                person_id = str(reporter)
                display_name = person_id

            if person_id:
                people.append(
                    (PersonInfo(id=person_id, display_name=display_name), "reporter")
                )

        assignee = doc.metadata.get("assignee")

        if assignee:
            if isinstance(assignee, dict):
                person_id = (
                    assignee.get("email_address")
                    or assignee.get("account_id")
                    or assignee.get("display_name")
                )
                display_name = assignee.get("display_name", person_id)
            else:
                person_id = str(assignee)
                display_name = person_id

            if person_id:
                people.append(
                    (PersonInfo(id=person_id, display_name=display_name), "assignee")
                )

        return people

    # ------------------------------------------------------------------
    # Container
    # ------------------------------------------------------------------

    def _extract_container(
        self,
        doc: Document,
    ) -> GraphNode | None:
        project_key = doc.metadata.get("project_key")

        if not project_key:
            return None

        return GraphNode(
            id=project_key,
            label=CoreNodeLabel.CONTAINER.value,
            project=project_key,
            properties={
                "kind": "jira_project",
                "project_key": project_key,
            },
        )

    # ------------------------------------------------------------------
    # Labels
    # ------------------------------------------------------------------

    def _extract_labels(
        self,
        doc: Document,
    ) -> list[GraphNode]:
        project = self._project(doc)
        metadata = doc.metadata
        nodes: list[GraphNode] = []

        for label in metadata.get("labels", []):
            nodes.append(
                GraphNode(
                    id=label,
                    label=CoreNodeLabel.LABEL.value,
                    project=project,
                    properties={
                        "name": label,
                    },
                )
            )

        return nodes

    # ------------------------------------------------------------------
    # Cross-source URL links
    # ------------------------------------------------------------------
    def _extract_links(
        self,
        doc: Document,
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        project = self._project(doc)
        metadata = doc.metadata
        text = metadata.get("description") or getattr(doc, "content", "") or ""

        nodes: list[GraphNode] = []
        edges: list[GraphEdge] = []

        def _is_url(value: str) -> bool:
            try:
                parsed = urlparse(value)
                return bool(parsed.scheme and parsed.netloc)
            except Exception:
                return False

        def _handle_url(url: str, kind: str) -> None:
            target = url.strip()

            if _is_url(target):
                nodes.append(
                    GraphNode(
                        id=target,
                        label=CoreNodeLabel.URL.value,
                        project=project,
                        properties={"url": target},
                    )
                )

            edges.append(
                GraphEdge(
                    source=metadata.get("key"),
                    target=target,
                    edge_type=CoreEdgeType.LINKS_TO.value,
                    project=project,
                    properties={"kind": kind},
                )
            )

        for url in self.CONFLUENCE_URL_RE.findall(text):
            _handle_url(url, "confluence")

        for url in self.GIT_URL_RE.findall(text):
            _handle_url(url, "git")

        return nodes, edges

    # ------------------------------------------------------------------
    # Jira-specific relationships
    # ------------------------------------------------------------------

    def _extract_source_specific(
        self,
        doc: Document,
    ) -> tuple[list[GraphNode], list[GraphEdge]]:
        project = self._project(doc)

        edges: list[GraphEdge] = []

        metadata = doc.metadata

        # --------------------------------------------------------------
        # Linked Issues
        # --------------------------------------------------------------

        for link in metadata.get("linked_issues", []):
            if isinstance(link, dict):
                target_key = link.get("key")
                kind = link.get("relation") or link.get("link_type") or "related"
                direction = link.get("direction")
            else:
                # Backward-compat: plain issue key string, no type/direction info.
                target_key = link
                kind = "related"
                direction = None

            if not target_key:
                continue

            properties = {"kind": kind}
            if direction:
                properties["direction"] = direction

            edges.append(
                GraphEdge(
                    source=metadata.get("key"),
                    target=target_key,
                    edge_type=CoreEdgeType.LINKS_TO.value,
                    project=project,
                    properties=properties,
                )
            )
        # --------------------------------------------------------------
        # Parent Issue
        # --------------------------------------------------------------

        parent_issue = metadata.get("parent_key")

        if parent_issue:
            # Jira's "parent" field means "subtask of" for issue_type=Sub-task, but
            # for other types (Story/Task/Bug) it means "child of an Epic" instead —
            # derive the relation from issue_type rather than assuming subtask.
            issue_type = (metadata.get("issue_type") or "").strip().lower()
            kind = "subtask" if issue_type in {"sub-task", "subtask"} else "child"

            edges.append(
                GraphEdge(
                    source=metadata.get("key"),
                    target=parent_issue,
                    edge_type=CoreEdgeType.PART_OF.value,
                    project=project,
                    properties={
                        "kind": kind,
                    },
                )
            )

        return [], edges
