"""Unit coverage for ConfluenceDocumentTransform.transform().

This class merges untrusted comment HTML into canonical content and merges
provenance/relations between the freshly-normalized page and the document
produced by an earlier pipeline stage -- it previously had 0% functional
coverage (the only existing test asserted the factory could instantiate it,
never called `.transform()`).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from confluence_test_helpers import full_content

from harborrag_adapters.connectors.confluence.document_transform import (
    ConfluenceDocumentTransform,
)
from harborrag_core.domain import (
    Document,
    DocumentProvenance,
    DocumentRelation,
    ParsedDocument,
    RawDocument,
)

pytestmark = [pytest.mark.unit, pytest.mark.whitebox]


def _raw_document(*, comments: list[dict] | None = None) -> RawDocument:
    return RawDocument(
        id="confluence://ENG/1",
        source="https://example.atlassian.net/wiki/spaces/ENG/pages/1",
        content="<p>Hello <b>World</b></p>",
        content_type="text/html",
        metadata={"space_key": "ENG", "comments": comments or []},
        raw=full_content("1"),
    )


def _parsed_document() -> ParsedDocument:
    return ParsedDocument(content="Hello World", parser_name="confluence")


def _document(
    *,
    author: str = "prior-author",
    tags: list[str] | None = None,
    extra: dict | None = None,
    relations: list[DocumentRelation] | None = None,
) -> Document:
    created_at = datetime(2024, 1, 1, tzinfo=UTC)
    updated_at = datetime(2024, 6, 1, tzinfo=UTC)
    return Document(
        id="confluence://ENG/1",
        title="Page One",
        content=[],
        content_type="page",
        provenance=DocumentProvenance(
            source="confluence",
            author=author,
            checksum="prior-checksum",
            created_at=created_at,
            updated_at=updated_at,
            tags=tags if tags is not None else ["prior-tag"],
            extra=extra if extra is not None else {"prior_only": "kept"},
        ),
        relations=relations if relations is not None else [],
    )


def test_transform_requires_raw_source_payload():
    transform = ConfluenceDocumentTransform()
    raw = RawDocument(
        id="confluence://ENG/1",
        source="https://example.atlassian.net/wiki/spaces/ENG/pages/1",
        content="<p>Hello</p>",
        content_type="text/html",
        raw=None,
    )

    with pytest.raises(ValueError, match="requires the source payload"):
        transform.transform(raw, _parsed_document(), _document())


def test_transform_appends_no_comments_heading_when_there_are_no_comments():
    transform = ConfluenceDocumentTransform()

    result = transform.transform(_raw_document(), _parsed_document(), _document())

    assert not any(
        element.metadata.get("role") == "confluence.comment" for element in result.content
    )
    assert not any(element.content == "Comments" for element in result.content)


def test_transform_appends_comments_heading_and_strips_html_from_comment_bodies():
    transform = ConfluenceDocumentTransform()
    comments = [
        {
            "id": "c1",
            "body": "<p>Looks <b>great</b>, ship it.</p>",
            "author": "Carol",
            "created_at": "2024-05-01T00:00:00Z",
            "comment_kind": "PAGE_COMMENT",
        },
        {
            "id": "c2",
            "body": "<p>One nit: <code>typo</code> in section 2.</p>",
            "author": "Dave",
            "comment_kind": "INLINE_COMMENT",
            "parent_comment_id": "c1",
        },
    ]

    result = transform.transform(_raw_document(comments=comments), _parsed_document(), _document())

    heading = next(element for element in result.content if element.content == "Comments")
    assert heading.type == "heading"
    assert heading.metadata == {"level": 1}

    comment_elements = [
        element
        for element in result.content
        if element.metadata.get("role") == "confluence.comment"
    ]
    assert [element.content for element in comment_elements] == [
        "Looks great, ship it.",
        "One nit: typo in section 2.",
    ]
    assert comment_elements[0].metadata["comment_id"] == "c1"
    assert comment_elements[0].metadata["author"] == "Carol"
    assert comment_elements[0].metadata["comment_kind"] == "PAGE_COMMENT"
    assert "parent_comment_id" not in comment_elements[0].metadata
    assert comment_elements[1].metadata["parent_comment_id"] == "c1"
    assert comment_elements[1].metadata["comment_kind"] == "INLINE_COMMENT"


def test_transform_skips_comments_missing_an_id_or_body():
    transform = ConfluenceDocumentTransform()
    comments = [
        {"id": "", "body": "<p>no id, dropped</p>"},
        {"id": "c1", "body": "   "},
        {"id": "c2", "body": "<p>kept</p>"},
    ]

    result = transform.transform(_raw_document(comments=comments), _parsed_document(), _document())

    comment_elements = [
        element
        for element in result.content
        if element.metadata.get("role") == "confluence.comment"
    ]
    assert [element.metadata["comment_id"] for element in comment_elements] == ["c2"]


def test_transform_carries_document_provenance_fields_but_prefers_canonical_extra_on_conflict():
    transform = ConfluenceDocumentTransform()
    document = _document(
        author="Alice",
        tags=["prior-tag"],
        extra={"prior_only": "kept", "space_key": "should-be-overridden-by-canonical"},
    )

    result = transform.transform(_raw_document(), _parsed_document(), document)

    # author/checksum/created_at/updated_at/tags come from the prior stage's
    # Document, not the freshly re-derived canonical provenance.
    assert result.provenance.author == "Alice"
    assert result.provenance.checksum == "prior-checksum"
    assert result.provenance.created_at == datetime(2024, 1, 1, tzinfo=UTC)
    assert result.provenance.updated_at == datetime(2024, 6, 1, tzinfo=UTC)
    assert result.provenance.tags == ["prior-tag"]
    # extra merges both dicts, but canonical's own extra wins on key overlap.
    assert result.provenance.extra["prior_only"] == "kept"
    assert result.provenance.extra["space_key"] != "should-be-overridden-by-canonical"


def test_transform_merges_relations_deduplicating_by_predicate_target_and_type():
    transform = ConfluenceDocumentTransform()
    prior_relation = DocumentRelation(
        predicate="has_attachment",
        target_id="confluence://ENG/1/attachments/a1",
        target_type="document",
        metadata={"source_relation_version": "prior"},
    )
    document = _document(relations=[prior_relation])

    result = transform.transform(_raw_document(), _parsed_document(), document)

    # The prior-stage relation (attachment) has no canonical counterpart, so
    # it survives the merge untouched.
    matching = [
        relation
        for relation in result.relations
        if (relation.predicate, relation.target_id, relation.target_type)
        == ("has_attachment", "confluence://ENG/1/attachments/a1", "document")
    ]
    assert matching == [prior_relation]


def test_merge_relations_prefers_the_first_group_on_key_collision():
    # ConfluenceDocumentTransform._merge_relations is called as
    # `_merge_relations(canonical.relations, document.relations)` -- the
    # canonical (freshly re-derived) copy must win when both groups produce
    # a relation with the same (predicate, target_id, target_type) key.
    canonical_relation = DocumentRelation(
        predicate="has_attachment",
        target_id="confluence://ENG/1/attachments/a1",
        target_type="document",
        metadata={"source_relation_version": "fresh"},
    )
    stale_relation = DocumentRelation(
        predicate="has_attachment",
        target_id="confluence://ENG/1/attachments/a1",
        target_type="document",
        metadata={"source_relation_version": "stale"},
    )

    merged = ConfluenceDocumentTransform._merge_relations([canonical_relation], [stale_relation])

    assert merged == [canonical_relation]


_FILE_UUID = "e49188de-7713-4f2f-90f6-189d20aa15c9"


def _body_media(media_id: str = _FILE_UUID) -> DocumentRelation:
    return DocumentRelation(
        predicate="has_attachment",
        target_id=media_id,
        target_type="attachment",
        metadata={"media_id": media_id},
    )


def _listed(file_id: str = _FILE_UUID) -> DocumentRelation:
    return DocumentRelation(
        predicate="has_attachment",
        target_id="confluence://ENG/1/attachments/att44269579",
        target_type="document",
        metadata={"file_id": file_id},
    )


def test_drop_superseded_attachment_refs_drops_only_the_reference_whose_file_is_listed():
    other_file = _body_media("11111111-2222-3333-4444-555555555555")
    link = DocumentRelation(
        predicate="links_to",
        target_id="confluence://ENG/2",
        target_type="document",
    )

    kept = ConfluenceDocumentTransform._drop_superseded_attachment_refs(
        [_body_media(), other_file, link],
        [_listed()],
    )

    assert kept == [other_file, link]


def test_drop_superseded_attachment_refs_matches_file_ids_case_insensitively():
    kept = ConfluenceDocumentTransform._drop_superseded_attachment_refs(
        [_body_media(_FILE_UUID.upper())],
        [_listed(_FILE_UUID)],
    )

    assert kept == []


def test_drop_superseded_attachment_refs_keeps_references_when_no_file_id_is_listed():
    body_media = _body_media()
    listed_without_file_id = DocumentRelation(
        predicate="has_attachment",
        target_id="confluence://ENG/1/attachments/att44269579",
        target_type="document",
    )

    kept = ConfluenceDocumentTransform._drop_superseded_attachment_refs(
        [body_media],
        [listed_without_file_id],
    )

    assert kept == [body_media]


def test_drop_superseded_attachment_refs_keeps_references_when_no_list_was_supplied():
    body_media = _body_media()

    kept = ConfluenceDocumentTransform._drop_superseded_attachment_refs([body_media], [])

    assert kept == [body_media]
