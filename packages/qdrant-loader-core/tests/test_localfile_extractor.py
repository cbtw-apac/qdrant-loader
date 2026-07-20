import pytest
from qdrant_loader.core.document import Document
from qdrant_loader_core.graph.extractor.localfile import LocalFileEntityExtractor


@pytest.mark.asyncio
async def test_localfile_basic():
    extractor = LocalFileEntityExtractor()

    metadata = {
        "file_name": "design_doc.md",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
    }

    doc = Document(
        title="Design Doc",
        content_type="page",
        content="Example content",
        source_type="localfile",
        source="localfile_instance",
        url="D:/docs/design_doc.md",
        metadata=metadata,
    )

    result = await extractor.extract(doc)

    assert any(n.label == "Document" for n in result.nodes)
    assert any(n.label == "Container" for n in result.nodes)
    assert any(e.edge_type == "BELONGS_TO" for e in result.edges)


@pytest.mark.asyncio
async def test_localfile_without_url_has_no_container():
    extractor = LocalFileEntityExtractor()

    doc = Document(
        title="No URL",
        content_type="page",
        content="content",
        source_type="localfile",
        source="localfile_instance",
        url="",
        metadata={"file_name": "notes.md"},
    )

    result = await extractor.extract(doc)

    assert not any(n.label == "Container" for n in result.nodes)
    assert not any(e.edge_type == "BELONGS_TO" for e in result.edges)
