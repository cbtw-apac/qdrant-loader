import pytest
from qdrant_loader.core.document import Document
from qdrant_loader_core.graph.extractor.jira import JiraEntityExtractor


@pytest.mark.asyncio
async def test_jira_basic():
    extractor = JiraEntityExtractor()

    metadata = {
        "project_key": "ABC",
        "status": "Open",
        "priority": "High",
        "issue_type": "Bug",
        "reporter": {
            "email_address": "reporter@company.com",
            "display_name": "Reporter",
        },
        "assignee": {
            "email_address": "john@company.com",
            "display_name": "John",
        },
        "labels": ["backend"],
        "description": "Related confluence page: http://confluence.example.com/display/ABC/Page",
    }

    doc = Document(
        title="Fix login bug",
        content_type="issue",
        content="Jira issue content",
        source_type="jira",
        source="ABC-1",
        url="http://jira/ABC-1",
        metadata=metadata,
    )

    result = await extractor.extract(doc)
    print([n.label for n in result.nodes])
    print([e.edge_type for e in result.edges])

    assert any(n.label == "Document" for n in result.nodes)
    assert any(n.label == "Container" for n in result.nodes)
    assert any(n.label == "Person" for n in result.nodes)

    assert any(e.edge_type == "BELONGS_TO" for e in result.edges)
    assert any(e.edge_type == "AUTHORED_BY" for e in result.edges)
    assert any(e.edge_type == "LINKS_TO" for e in result.edges)


@pytest.mark.asyncio
async def test_jira_linked_issues_preserve_relation_and_direction():
    extractor = JiraEntityExtractor()

    metadata = {
        "key": "ABC-1",
        "project_key": "ABC",
        "status": "Open",
        "priority": "High",
        "issue_type": "Bug",
        "linked_issues": [
            {
                "key": "ABC-2",
                "link_type": "Cloners",
                "direction": "outward",
                "relation": "clones",
            },
            {
                "key": "ABC-3",
                "link_type": "Cloners",
                "direction": "inward",
                "relation": "is cloned by",
            },
            # Backward-compat: plain string key, no type/direction metadata.
            "ABC-4",
        ],
    }

    doc = Document(
        title="Fix login bug",
        content_type="issue",
        content="Jira issue content",
        source_type="jira",
        source="ABC-1",
        url="http://jira/ABC-1",
        metadata=metadata,
    )

    result = await extractor.extract(doc)
    link_edges = {e.target: e for e in result.edges if e.source == "ABC-1"}

    assert link_edges["ABC-2"].properties["kind"] == "clones"
    assert link_edges["ABC-2"].properties["direction"] == "outward"

    assert link_edges["ABC-3"].properties["kind"] == "is cloned by"
    assert link_edges["ABC-3"].properties["direction"] == "inward"

    assert link_edges["ABC-4"].properties["kind"] == "related"
    assert "direction" not in link_edges["ABC-4"].properties


@pytest.mark.asyncio
async def test_jira_parent_edge_kind_derived_from_issue_type():
    extractor = JiraEntityExtractor()

    subtask_doc = Document(
        title="Subtask",
        content_type="issue",
        content="content",
        source_type="jira",
        source="ABC-1",
        url="http://jira/ABC-1",
        metadata={
            "key": "ABC-1",
            "project_key": "ABC",
            "issue_type": "Sub-task",
            "parent_key": "ABC-0",
        },
    )
    story_doc = Document(
        title="Story",
        content_type="issue",
        content="content",
        source_type="jira",
        source="ABC-2",
        url="http://jira/ABC-2",
        metadata={
            "key": "ABC-2",
            "project_key": "ABC",
            "issue_type": "Story",
            "parent_key": "ABC-EPIC",
        },
    )

    subtask_result = await extractor.extract(subtask_doc)
    story_result = await extractor.extract(story_doc)

    subtask_edge = next(
        e for e in subtask_result.edges if e.edge_type == "PART_OF"
    )
    story_edge = next(e for e in story_result.edges if e.edge_type == "PART_OF")

    assert subtask_edge.properties["kind"] == "subtask"
    assert story_edge.properties["kind"] == "child"
