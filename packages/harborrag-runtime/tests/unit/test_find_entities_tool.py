"""Tests for find_entities ranking, facet filters and released evidence."""

from typing import NoReturn

import pytest
from test_entity_summary_search import PROFILE, Vectors, entity_hit

from harborrag_core.contracts.reader import (
    ENTITIES_WITHOUT_RELEASED_EVIDENCE,
    ENTITY_INDEX_UNAVAILABLE,
    EntityFindRequest,
    EntityFindResponse,
    EntityMatch,
)
from harborrag_core.indexing import VectorFilter, VectorFilterCondition
from harborrag_core.security import AccessContext
from harborrag_core.storage import StorageOperationContext
from harborrag_core.summaries import SummaryAttribute, SummaryCard, SummaryView
from harborrag_engine.tools.catalog import build_reader_tool_catalog
from harborrag_engine.tools.find_entities import FindEntitiesTool
from harborrag_engine.tools.references import KnowledgeReferenceStore
from harborrag_runtime.retrieval.entity_summary import EntitySummarySearch

pytestmark = pytest.mark.unit


class Retrieval:
    def __init__(self) -> None:
        self.requests: list[EntityFindRequest] = []

    async def search(self, request: object) -> NoReturn:  # pragma: no cover - not exercised here
        raise AssertionError("search is not the tool under test")

    async def find_entities(self, request: EntityFindRequest) -> EntityFindResponse:
        self.requests.append(request)
        return EntityFindResponse(
            "entities-1",
            (
                EntityMatch(
                    node_key="node-a",
                    source_scope_id="AUTA-2",
                    rank=1,
                    score=0.91,
                    description="Senior Java engineer, banking, cleared round two.",
                    coverage_mode="partial",
                    attributes=(
                        {
                            "name": "stage",
                            "values": ["round 2"],
                            "from_document_ids": ["doc-issue"],
                        },
                    ),
                    evidence_chunk_ids=("chunk-1", "chunk-2"),
                ),
            ),
            truncated=True,
        )


@pytest.mark.asyncio
async def test_the_tool_passes_facets_through_and_reports_partial_coverage() -> None:
    """A truncated answer tells the caller that more entities qualified."""
    retrieval = Retrieval()
    tool = FindEntitiesTool(retrieval=retrieval, references=KnowledgeReferenceStore())
    result = await tool.call(
        {
            "tenant_id": "AUTA-2",
            "query": "senior java engineer with banking experience",
            "facets": {"stage": "round 2", "years_experience": {"gte": 5}},
            "source_ids": ["AUTA-2"],
            "limit": 5,
        },
        principal_id="recruiter-1",
    )
    request = retrieval.requests[0]
    assert request.facets == {"stage": "round 2", "years_experience": {"gte": 5}}
    assert request.source_scope_ids == ("AUTA-2",)
    assert request.limit == 5
    assert str(request.access.tenant_id) == "AUTA-2"
    assert result["ok"] is True
    match = result["matches"][0]
    assert match["node_key"] == "node-a"
    assert match["coverage_mode"] == "partial"
    assert match["attributes"][0]["values"] == ["round 2"]
    assert match["evidence_chunk_ids"] == ["chunk-1", "chunk-2"]
    assert result["completion"] == {"complete": False, "reasons": ["candidate_limit"]}


@pytest.mark.asyncio
async def test_bad_arguments_and_a_missing_backend_are_failures_not_exceptions() -> None:
    tool = FindEntitiesTool(retrieval=Retrieval(), references=KnowledgeReferenceStore())
    blank = await tool.call({"tenant_id": "AUTA-2", "query": "  "}, principal_id="p")
    assert blank["ok"] is False
    too_many = await tool.call(
        {"tenant_id": "AUTA-2", "query": "q", "limit": 500}, principal_id="p"
    )
    assert too_many["ok"] is False
    unconfigured = FindEntitiesTool(references=KnowledgeReferenceStore())
    missing = await unconfigured.call({"tenant_id": "AUTA-2", "query": "q"}, principal_id="p")
    assert missing["ok"] is False and "not configured" in missing["error"]


def test_the_tool_is_in_the_shared_catalog_and_read_only() -> None:
    tools = build_reader_tool_catalog(None, KnowledgeReferenceStore())
    spec = next(tool.spec for tool in tools if tool.spec.name == "find_entities")
    assert spec.behavior.read_only and spec.behavior.idempotent
    assert set(spec.input_schema["required"]) == {"tenant_id", "query"}
    assert "facets" in spec.input_schema["properties"]


class Summaries:
    async def entity_evidence(
        self, tenant_id: str, node_keys: tuple[str, ...], *, access: AccessContext
    ) -> dict[str, tuple[str, ...]]:
        return {}

    async def views(self, *args: object, **kwargs: object) -> dict[str, SummaryView]:
        return {}


@pytest.mark.asyncio
async def test_ranked_hits_carry_scope_and_coverage_and_drop_foreign_points() -> None:
    base = entity_hit("node-a")
    good = base.model_copy(update={"payload": {**base.payload, "coverage_mode": "complete"}})
    other = entity_hit("node-b")
    foreign = other.model_copy(
        update={"payload": {**other.payload, "record_kind": "parent_description"}}
    )
    vectors = Vectors(records={PROFILE.entity_index_name: {}}, hits=(good, foreign, good))
    search = EntitySummarySearch(Summaries(), vectors, PROFILE)
    hits = await search.ranked_entities(
        (1.0, 0.0),
        StorageOperationContext.system("DEFAULT"),
        VectorFilter(must=[VectorFilterCondition(field="facet.stage", value="round 2")]),
    )
    assert [(hit.node_key, hit.source_scope_id, hit.coverage_mode) for hit in hits] == [
        ("node-a", "scope", "complete")
    ]


class Unindexed(Retrieval):
    """A retrieval backend whose tenant has no entity index published yet."""

    async def find_entities(self, request: EntityFindRequest) -> EntityFindResponse:
        self.requests.append(request)
        return EntityFindResponse("entities-2", (), reasons=(ENTITY_INDEX_UNAVAILABLE,))


@pytest.mark.asyncio
async def test_a_missing_index_is_an_incomplete_answer_not_an_empty_one() -> None:
    """A missing index says it could not look, never that nothing matched."""
    tool = FindEntitiesTool(retrieval=Unindexed(), references=KnowledgeReferenceStore())
    result = await tool.call({"tenant_id": "AUTA-5", "query": "java"}, principal_id="p")
    assert result["ok"] is True
    assert result["matches"] == []
    assert result["withheld_entity_count"] == 0
    assert result["completion"] == {"complete": False, "reasons": [ENTITY_INDEX_UNAVAILABLE]}
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(result, tool.spec.output_schema)


def test_the_description_says_when_to_fall_back_to_chunk_search() -> None:
    tools = build_reader_tool_catalog(None, KnowledgeReferenceStore())
    spec = next(tool.spec for tool in tools if tool.spec.name == "find_entities")
    assert ENTITY_INDEX_UNAVAILABLE in spec.description
    assert "vector_search" in spec.description
    assert "list_sources" in spec.description


class Released:
    """The authority releases a card and evidence only for the keys it is given."""

    def __init__(self, released: set[str]) -> None:
        self.released = released

    async def entity_evidence(
        self, tenant_id: str, node_keys: tuple[str, ...], *, access: AccessContext
    ) -> dict[str, tuple[str, ...]]:
        return {key: ("chunk-" + key,) for key in node_keys if key in self.released}

    async def views(
        self,
        tenant_id: str,
        node_keys: tuple[str, ...],
        *,
        access: AccessContext,
        source_scopes: dict[str, str] | None = None,
    ) -> dict[str, SummaryView]:
        card = SummaryCard(
            description="Senior Java engineer.",
            attributes=(SummaryAttribute(name="skill_set", values=("BE-Java",)),),
        )
        return {
            key: SummaryView(status="current", card=card, coverage_mode="complete")
            for key in node_keys
            if key in self.released
        }


def _request(corpus_mode: str = "tenant_shared", limit: int = 5) -> EntityFindRequest:
    access = AccessContext(tenant_id="DEFAULT", principal_id="p", corpus_mode=corpus_mode)
    return EntityFindRequest(access=access, query="java", limit=limit)


@pytest.mark.asyncio
async def test_find_reports_a_tenant_without_an_entity_index() -> None:
    search = EntitySummarySearch(Released(set()), Vectors(), PROFILE)
    response = await search.find(
        _request(), "entities-x", (1.0, 0.0), StorageOperationContext.system("DEFAULT")
    )
    assert response.matches == ()
    assert response.reasons == (ENTITY_INDEX_UNAVAILABLE,)


@pytest.mark.asyncio
async def test_an_existing_index_with_no_match_is_a_complete_empty_answer() -> None:
    vectors = Vectors(records={PROFILE.entity_index_name: {}}, hits=())
    search = EntitySummarySearch(Released(set()), vectors, PROFILE)
    response = await search.find(
        _request(), "entities-x", (1.0, 0.0), StorageOperationContext.system("DEFAULT")
    )
    assert response.matches == () and response.reasons == () and not response.truncated


@pytest.mark.asyncio
async def test_hits_with_no_released_summary_are_counted_on_a_shared_corpus() -> None:
    vectors = Vectors(
        records={PROFILE.entity_index_name: {}},
        hits=(entity_hit("node-a"), entity_hit("node-b"), entity_hit("node-c")),
    )
    search = EntitySummarySearch(Released({"node-b"}), vectors, PROFILE)
    response = await search.find(
        _request(), "entities-x", (1.0, 0.0), StorageOperationContext.system("DEFAULT")
    )
    assert [match.node_key for match in response.matches] == ["node-b"]
    assert response.matches[0].rank == 1
    assert response.matches[0].evidence_chunk_ids == ("chunk-node-b",)
    assert response.matches[0].attributes[0]["values"] == ["BE-Java"]
    assert response.reasons == (ENTITIES_WITHOUT_RELEASED_EVIDENCE,)
    assert response.withheld_count == 2

    tool = FindEntitiesTool(retrieval=_Fixed(response), references=KnowledgeReferenceStore())
    result = await tool.call({"tenant_id": "DEFAULT", "query": "java"}, principal_id="p")
    assert result["withheld_entity_count"] == 2
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(result, tool.spec.output_schema)
    assert result["completion"] == {
        "complete": False,
        "reasons": [ENTITIES_WITHOUT_RELEASED_EVIDENCE],
    }


@pytest.mark.asyncio
async def test_unreleased_hits_stay_silent_under_source_acls() -> None:
    """Under source ACLs a count would say how many private entities match."""
    vectors = Vectors(
        records={PROFILE.entity_index_name: {}},
        hits=(entity_hit("node-a"), entity_hit("node-b")),
    )
    search = EntitySummarySearch(Released({"node-b"}), vectors, PROFILE)
    response = await search.find(
        _request("source_acl"), "entities-x", (1.0, 0.0), StorageOperationContext.system("DEFAULT")
    )
    assert [match.node_key for match in response.matches] == ["node-b"]
    assert response.reasons == () and response.withheld_count == 0


@pytest.mark.asyncio
async def test_more_released_entities_than_the_limit_is_truncation() -> None:
    vectors = Vectors(
        records={PROFILE.entity_index_name: {}},
        hits=(entity_hit("node-a"), entity_hit("node-b"), entity_hit("node-c")),
    )
    search = EntitySummarySearch(Released({"node-a", "node-b", "node-c"}), vectors, PROFILE)
    response = await search.find(
        _request(limit=2), "entities-x", (1.0, 0.0), StorageOperationContext.system("DEFAULT")
    )
    assert [match.node_key for match in response.matches] == ["node-a", "node-b"]
    assert response.truncated and response.reasons == ()


def _ranked(*node_keys: str) -> Vectors:
    return Vectors(
        records={PROFILE.entity_index_name: {}},
        hits=tuple(entity_hit(key) for key in node_keys),
    )


@pytest.mark.asyncio
async def test_find_under_source_acls_with_every_hit_withheld_reports_no_truncation() -> None:
    """Hidden entities filling the window must not read as ``candidate_limit``.

    That reason would tell a source-ACL reader that more than ``limit`` hidden
    entities match their facets.
    """
    search = EntitySummarySearch(Released(set()), _ranked("node-a", "node-b", "node-c"), PROFILE)
    response = await search.find(
        _request("source_acl", limit=2),
        "entities-x",
        (1.0, 0.0),
        StorageOperationContext.system("DEFAULT"),
    )
    assert response.matches == ()
    assert not response.truncated
    assert response.reasons == () and response.withheld_count == 0

    tool = FindEntitiesTool(retrieval=_Fixed(response), references=KnowledgeReferenceStore())
    result = await tool.call({"tenant_id": "DEFAULT", "query": "java"}, principal_id="p")
    assert "candidate_limit" not in result["completion"]["reasons"]


@pytest.mark.asyncio
async def test_find_under_source_acls_with_more_visible_hits_than_the_limit_is_truncated() -> None:
    search = EntitySummarySearch(
        Released({"node-a", "node-b", "node-c"}),
        _ranked("node-a", "node-b", "node-c"),
        PROFILE,
    )
    response = await search.find(
        _request("source_acl", limit=2),
        "entities-x",
        (1.0, 0.0),
        StorageOperationContext.system("DEFAULT"),
    )
    assert [match.node_key for match in response.matches] == ["node-a", "node-b"]
    assert response.truncated and response.reasons == ()


@pytest.mark.asyncio
async def test_find_under_source_acls_with_one_hit_withheld_returns_limit_untruncated() -> None:
    """Only ``limit`` visible entities matched, so the answer is not cut short."""
    search = EntitySummarySearch(
        Released({"node-a", "node-c"}), _ranked("node-a", "node-b", "node-c"), PROFILE
    )
    response = await search.find(
        _request("source_acl", limit=2),
        "entities-x",
        (1.0, 0.0),
        StorageOperationContext.system("DEFAULT"),
    )
    assert [match.node_key for match in response.matches] == ["node-a", "node-c"]
    assert [match.rank for match in response.matches] == [1, 2]
    assert not response.truncated
    assert response.reasons == () and response.withheld_count == 0


@pytest.mark.asyncio
async def test_find_on_a_shared_corpus_ignores_withheld_hits_past_the_limit() -> None:
    """A withheld hit past a full limit is not counted and does not hide truncation."""
    search = EntitySummarySearch(
        Released({"node-a", "node-b"}), _ranked("node-a", "node-b", "node-c"), PROFILE
    )
    response = await search.find(
        _request(limit=2), "entities-x", (1.0, 0.0), StorageOperationContext.system("DEFAULT")
    )
    assert [match.node_key for match in response.matches] == ["node-a", "node-b"]
    assert response.truncated
    assert response.reasons == () and response.withheld_count == 0


class _Fixed(Retrieval):
    def __init__(self, response: EntityFindResponse) -> None:
        super().__init__()
        self.response = response

    async def find_entities(self, request: EntityFindRequest) -> EntityFindResponse:
        return self.response
