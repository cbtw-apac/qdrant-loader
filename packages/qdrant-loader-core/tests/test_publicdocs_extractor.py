from __future__ import annotations

import pytest
from qdrant_loader.core.document import Document
from qdrant_loader_core.graph.extractor.publicdocs import PublicDocsEntityExtractor


@pytest.mark.asyncio
async def test_public_webpage():
    extractor = PublicDocsEntityExtractor()

    metadata = {
        "url": "https://example.com/page",
        "tags": ["ai", "ml"],
        "links": ["https://example.com/other"],
        "attachments": [
            {"id": "att1", "filename": "doc.pdf", "mime_type": "application/pdf"}
        ],
    }

    doc = Document(
        title="Example Page",
        content_type="page",
        content="Example webpage content",
        source_type="publicdocs",
        source="https://example.com/page",
        url="https://example.com/page",
        metadata=metadata,
    )

    result = await extractor.extract(doc)

    assert any(n.label == "Document" for n in result.nodes)
    assert any(n.label == "Label" for n in result.nodes)
    assert any(n.label == "Container" for n in result.nodes), "Container node missing"
    assert any(n.label == "Attachment" for n in result.nodes), "Attachment node missing"
    assert any(e.edge_type == "HAS_LABEL" for e in result.edges)
    assert any(e.edge_type == "LINKS_TO" for e in result.edges), "LINKS_TO edge missing"
    assert any(
        e.edge_type == "HAS_ATTACHMENT" for e in result.edges
    ), "HAS_ATTACHMENT edge missing"


@pytest.mark.asyncio
async def test_public_webpage_without_url_has_no_project_or_container():
    extractor = PublicDocsEntityExtractor()

    doc = Document(
        title="No URL page",
        content_type="page",
        content="content",
        source_type="publicdocs",
        source="no-url-source",
        url="",
        metadata={},
    )

    result = await extractor.extract(doc)

    assert not any(n.label == "Container" for n in result.nodes)
    assert all(n.project is None for n in result.nodes)


@pytest.mark.asyncio
async def test_public_webpage_with_domain_less_url_has_no_container():
    extractor = PublicDocsEntityExtractor()

    doc = Document(
        title="Relative URL page",
        content_type="page",
        content="content",
        source_type="publicdocs",
        source="relative-source",
        url="not-a-real-url",
        metadata={"url": "not-a-real-url"},
    )

    result = await extractor.extract(doc)

    assert not any(n.label == "Container" for n in result.nodes)


@pytest.mark.asyncio
async def test_public_webpage_attachment_missing_id_is_skipped():
    extractor = PublicDocsEntityExtractor()

    doc = Document(
        title="Page with malformed attachment",
        content_type="page",
        content="content",
        source_type="publicdocs",
        source="https://example.com/page5",
        url="https://example.com/page5",
        metadata={"attachments": [{"filename": "no_id.pdf"}]},
    )

    result = await extractor.extract(doc)

    assert not any(n.label == "Attachment" for n in result.nodes)
    assert not any(e.edge_type == "HAS_ATTACHMENT" for e in result.edges)
