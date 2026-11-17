from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from harborrag_adapters.connectors.attachments import (
    AttachmentSourceGateway,
    attachment_source_record,
    select_attachment_payloads,
)
from harborrag_adapters.connectors.descriptors import (
    ConnectorDocumentDescriptor,
)
from harborrag_core.chunking import RelationType
from harborrag_core.domain.source import SourceRecord
from harborrag_core.ingestion import (
    AdmissionSnapshot,
    SourceObjectVersion,
    SourceRelationDescriptor,
)

from .config import ConfluenceSpaceConfig
from .content import ConfluenceContentAPI
from .mappers import build_source_record, content_id_from_record, validate_content
from .normalization.schemas import space_identity

DISCOVERY_DESCRIPTOR_KEY = "_confluence_discovery_descriptor"


def _file_id(attachment: Mapping[str, Any] | None) -> str:
    """The file UUID an attachment's body media node references, or '' when absent."""

    if not attachment:
        return ""
    extensions = attachment.get("extensions") or {}
    return str(extensions.get("fileId") or "").strip().casefold()


class ConfluenceDescriptorBuilder:
    """Build page admission data and attachment records without downloading bytes."""

    def __init__(
        self,
        *,
        content: ConfluenceContentAPI,
        attachments: AttachmentSourceGateway,
        config: ConfluenceSpaceConfig,
        base_url: str,
    ) -> None:
        self._content = content
        self._attachments = attachments
        self._config = config
        self._base_url = base_url

    def describe(
        self,
        record: SourceRecord,
    ) -> ConnectorDocumentDescriptor:
        content_id = content_id_from_record(record)
        cached = record.metadata.get(DISCOVERY_DESCRIPTOR_KEY)
        content = (
            dict(cached)
            if isinstance(cached, dict)
            else self._content.get_content_descriptor(content_id)
        )
        validate_content(content, content_id, space_key=self._config.space_key)
        discovered = build_source_record(
            content,
            base_url=self._base_url,
            deployment_type=self._config.deployment,
            default_space_key=self._config.space_key,
        )
        include_comments = bool(
            self._config.include_comments and record.metadata.get("include_comments", True)
        )
        comments = self._content.list_comment_descriptors(content_id) if include_comments else []
        include_attachments = bool(
            self._config.include_attachments and record.metadata.get("include_attachments", True)
        )
        raw_attachments = []
        if include_attachments:
            raw_attachments = select_attachment_payloads(
                self._content.list_attachments(content_id),
                tuple(
                    record.metadata.get(
                        "_selected_attachment_ids",
                        (),
                    )
                ),
            )
        attachment_descriptors = self._attachments.describe(raw_attachments)
        # The same space identity the page itself projects, so page and attachment land
        # under one space node instead of the attachment falling back to the data source.
        container = space_identity(
            content.get("space") or {},
            default_space_key=self._config.space_key,
        )
        bound_records = tuple(
            attachment_source_record(discovered, descriptor, inherited=container)
            for descriptor in attachment_descriptors
            if descriptor.status == "admitted"
        )
        source_version = self._source_version(content)
        # Each listed attachment's file UUID, keyed by its bound record id. A body media node
        # names the file by this UUID, so the relation carries it for the body-side match.
        raw_by_id = {str(item.get("id") or ""): item for item in raw_attachments}
        file_ids = {
            record.id: _file_id(raw_by_id.get(str(record.metadata.get("attachment_id") or "")))
            for record in bound_records
        }
        relations = self._relations(
            content,
            parent=discovered,
            attachments=bound_records,
            source_version=source_version,
        )
        source_metadata = {
            key: value
            for key, value in record.metadata.items()
            if key not in {"_selected_attachment_ids", DISCOVERY_DESCRIPTOR_KEY}
        }
        source = replace(
            record,
            updated_at=discovered.updated_at,
            metadata={
                **source_metadata,
                **discovered.metadata,
                "source_version": source_version,
                "defer_attachments": True,
                "attachment_names": [descriptor.title for descriptor in attachment_descriptors],
                "relations": [
                    self._relation_payload(
                        relation,
                        titles=self._ancestor_titles(content),
                        file_ids=file_ids,
                    )
                    for relation in relations
                ],
            },
        )
        return ConnectorDocumentDescriptor(
            source=source,
            admission=AdmissionSnapshot(
                source_version=source_version,
                comments=tuple(
                    SourceObjectVersion(
                        source_item_id=str(comment.get("id") or ""),
                        source_version=self._comment_version(comment),
                    )
                    for comment in comments
                    if str(comment.get("id") or "").strip()
                ),
                attachments=tuple(
                    SourceObjectVersion(
                        source_item_id=descriptor.attachment_id,
                        source_version=descriptor.source_version,
                    )
                    for descriptor in attachment_descriptors
                ),
                relations=relations,
            ),
            bound_records=bound_records,
        )

    @staticmethod
    def _source_version(content: dict[str, Any]) -> str:
        version = content.get("version") or {}
        value = version.get("number") or version.get("when")
        if value is None or not str(value).strip():
            raise ValueError("Confluence descriptor has no source version")
        return str(value)

    @staticmethod
    def _comment_version(comment: dict[str, Any]) -> str:
        version = comment.get("version") or {}
        history = comment.get("history") or {}
        updated = history.get("lastUpdated") or {}
        value = (
            version.get("number")
            or version.get("when")
            or updated.get("when")
            or history.get("createdDate")
            or history.get("createdAt")
        )
        if value is not None and str(value).strip():
            return str(value)
        return hashlib.sha256(
            json.dumps(
                {
                    "id": comment.get("id"),
                    "status": comment.get("status"),
                },
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _relations(
        content: dict[str, Any],
        *,
        parent: SourceRecord,
        attachments: tuple[SourceRecord, ...],
        source_version: str,
    ) -> tuple[SourceRelationDescriptor, ...]:
        values: list[SourceRelationDescriptor] = []
        ancestors = content.get("ancestors") or []
        if ancestors:
            parent_id = str(ancestors[-1].get("id") or "").strip()
            if parent_id:
                values.append(
                    SourceRelationDescriptor(
                        relation_type=RelationType.CHILD_OF,
                        target_source_item_id=(
                            f"confluence://{parent.metadata['space_key']}/{parent_id}"
                        ),
                        source_relation_version=source_version,
                    )
                )
        values.extend(
            SourceRelationDescriptor(
                relation_type=RelationType.HAS_ATTACHMENT,
                target_source_item_id=attachment.id,
                source_relation_version=str(attachment.metadata["source_version"]),
            )
            for attachment in attachments
        )
        return tuple(values)

    @staticmethod
    def _relation_payload(
        relation: SourceRelationDescriptor,
        *,
        titles: dict[str, str],
        file_ids: dict[str, str] | None = None,
    ) -> dict[str, object]:
        metadata: dict[str, object] = {"source_relation_version": relation.source_relation_version}
        # Carried on the payload, never on the descriptor: the descriptor feeds
        # admission_change_key, so adding a field there would re-admit every document.
        # The payload is not free either -- SourceAdmissionPolicy.retrieval_metadata_view
        # hashes document.relations, so adding this key re-versions every page that has a
        # relation, once. Measured on a live re-run: 84 of 98 pages took a second version
        # whose canonical_content_hash, processing_fingerprint and admission_change_key
        # were all unchanged. That is the intended trade -- it is what republished the
        # graph with resolved target titles -- but it is a re-embed, so do not add
        # cosmetic keys here.
        title = titles.get(relation.target_source_item_id)
        if title:
            metadata["target_title"] = title
        file_id = (file_ids or {}).get(relation.target_source_item_id)
        if file_id:
            metadata["file_id"] = file_id
        return {
            "predicate": relation.relation_type.value,
            "target_id": relation.target_source_item_id,
            "target_type": "document",
            "metadata": metadata,
        }

    @staticmethod
    def _ancestor_titles(content: dict[str, Any]) -> dict[str, str]:
        """Map each ancestor's canonical source id to its human title."""

        space_key = str((content.get("space") or {}).get("key") or "").strip()
        titles: dict[str, str] = {}
        for ancestor in content.get("ancestors") or []:
            ancestor_id = str(ancestor.get("id") or "").strip()
            title = str(ancestor.get("title") or "").strip()
            if ancestor_id and title and space_key:
                titles[f"confluence://{space_key}/{ancestor_id}"] = title
        return titles
