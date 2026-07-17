import pytest
from qdrant_loader.core.document import Document
from qdrant_loader_core.graph.extractor.confluence import ConfluenceEntityExtractor


@pytest.mark.asyncio
async def test_confluence_page():
    extractor = ConfluenceEntityExtractor()

    # Prepare a Document instance with normalized metadata the extractor expects
    metadata = {
        "space_key": "ENG",
        "author": "Bob",
        "labels": ["design"],
        "parent_id": None,
        "children": [{"id": "456"}],
    }

    doc = Document(
        title="Design Doc",
        content_type="page",
        content="Example content",
        source_type="confluence",
        source="confluence_instance",
        url="http://conf/page",
        metadata=metadata,
    )

    result = await extractor.extract(doc)

    assert any(n.label == "Container" for n in result.nodes)
    assert any(e.edge_type == "BELONGS_TO" for e in result.edges)


@pytest.mark.asyncio
async def test_confluence_page_without_author_has_no_person():
    extractor = ConfluenceEntityExtractor()

    doc = Document(
        title="No Author",
        content_type="page",
        content="content",
        source_type="confluence",
        source="confluence_instance",
        url="http://conf/page2",
        metadata={"space_key": "ENG"},
    )

    result = await extractor.extract(doc)

    assert not any(n.label == "Person" for n in result.nodes)
    assert not any(e.edge_type == "AUTHORED_BY" for e in result.edges)


@pytest.mark.asyncio
async def test_confluence_page_without_space_key_has_no_container():
    extractor = ConfluenceEntityExtractor()

    doc = Document(
        title="No Space",
        content_type="page",
        content="content",
        source_type="confluence",
        source="confluence_instance",
        url="http://conf/page3",
        metadata={},
    )

    result = await extractor.extract(doc)

    assert not any(n.label == "Container" for n in result.nodes)
    assert not any(e.edge_type == "BELONGS_TO" for e in result.edges)


@pytest.mark.asyncio
async def test_confluence_page_with_parent_and_children():
    extractor = ConfluenceEntityExtractor()

    doc = Document(
        title="Child Page",
        content_type="page",
        content="content",
        source_type="confluence",
        source="confluence_instance",
        url="http://conf/page4",
        metadata={
            "space_key": "ENG",
            "parent_id": "123",
            "children": [{"id": "789"}, {}],
        },
    )

    result = await extractor.extract(doc)

    part_of_edges = [e for e in result.edges if e.edge_type == "PART_OF"]
    has_child_edges = [e for e in result.edges if e.edge_type == "HAS_CHILD"]

    assert len(part_of_edges) == 1
    assert part_of_edges[0].target == "123"

    # The child entry without an "id" is skipped; only "789" produces an edge.
    assert len(has_child_edges) == 1
    assert has_child_edges[0].target == "789"
