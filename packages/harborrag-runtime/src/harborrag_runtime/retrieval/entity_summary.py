"""Entity-summary search for questions about a whole source entity.

Nothing is served from a summary point itself. The summary authority decides,
per request, which cards and evidence chunks a caller may read, and those chunks
go through the same permission checks as every other candidate.

Typical usage example:

    search = EntitySummarySearch(summaries, vectors, profile)
    response = await search.find(request, request_id, dense_vector, context)
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from dataclasses import dataclass

from harborrag_core.contracts.reader import (
    ENTITIES_WITHOUT_RELEASED_EVIDENCE,
    ENTITY_INDEX_UNAVAILABLE,
    EntityFindRequest,
    EntityFindResponse,
    EntityMatch,
)
from harborrag_core.indexing import (
    FilterOperator,
    VectorFilter,
    VectorFilterCondition,
    VectorSearchQuery,
    VectorSearchResult,
)
from harborrag_core.ingestion import DocumentIdentityBuilder
from harborrag_core.ports.storage import VectorRepositoryPort
from harborrag_core.ports.summary_projection import SummaryReaderPort
from harborrag_core.storage import StorageOperationContext
from harborrag_core.summaries import FACET_NAME_PATTERN, SummaryCard, SummaryView
from harborrag_core.topology.derived import (
    ENTITY_SUMMARY_RECORD_KIND,
    ContextualIndexProfile,
)
from harborrag_engine.retrieval.fusion import fuse_candidates

from .source_fields import PayloadIndexCatalog

_MAX_ENTITIES = 8
_MAX_CHUNKS_PER_ENTITY = 8
_MAX_SELECTED_ENTITIES = 50
"""Entities ranked when facet filters select rather than enrich.

The caller has said which entities count, so this is how many of them are ranked.
"""
FACET_FILTER_PREFIX = "facet."
UNKNOWN_FACET = "unknown_facet"
"""Reason code for a facet no source scope declared.

A filter on it cannot match anything, so the empty answer it produces is not a
conclusive one.
"""
_FACET_NAME = re.compile(FACET_NAME_PATTERN)


_RANGE_OPERATORS = {
    "gte": FilterOperator.GREATER_THAN_OR_EQUAL,
    "gt": FilterOperator.GREATER_THAN,
    "lte": FilterOperator.LESS_THAN_OR_EQUAL,
    "lt": FilterOperator.LESS_THAN,
}


def facet_filter_from_mapping(
    facets: Mapping[str, object], source_scope_ids: tuple[str, ...] = ()
) -> VectorFilter | None:
    """Build the entity-point filter for facet values and source scopes.

    Text facet values are matched case-folded, the way they were stored, so a
    caller's ``Java`` finds a card's ``java``. A name that no scope could have
    declared (``Skill Set`` instead of ``skill_set``) is refused, not searched.

    Args:
        facets: Facet name to a value, a list of values (any one matches), or a
            mapping of range bounds (``gte``, ``gt``, ``lte``, ``lt``) to numbers.
        source_scope_ids: Source scopes the entities must belong to. Empty means any.

    Returns:
        The entity-point filter, or None when there is nothing to filter on.

    Raises:
        ValueError: A facet name is malformed, or a range bound is unsupported or
            not a number.
    """
    must: list[VectorFilterCondition] = []
    for name, value in sorted(facets.items()):
        if not _FACET_NAME.fullmatch(name):
            raise ValueError(
                f"facet {name!r} is not a facet name; use the names list_sources gives "
                "as entity_facets"
            )
        field = f"{FACET_FILTER_PREFIX}{name}"
        if isinstance(value, Mapping):
            for bound, raw in value.items():
                operator = _RANGE_OPERATORS.get(str(bound))
                if operator is None or isinstance(raw, bool) or not isinstance(raw, (int, float)):
                    raise ValueError(f"facet {name!r} range bound {bound!r} is not supported")
                must.append(VectorFilterCondition(field=field, operator=operator, value=raw))
        elif isinstance(value, (list, tuple)):
            must.append(
                VectorFilterCondition(
                    field=field,
                    operator=FilterOperator.IN,
                    value=[_folded(item) for item in value],
                )
            )
        else:
            must.append(VectorFilterCondition(field=field, value=_folded(value)))
    if source_scope_ids:
        must.append(
            VectorFilterCondition(
                field="source_scope_id", operator=FilterOperator.IN, value=list(source_scope_ids)
            )
        )
    return VectorFilter(must=must) if must else None


def _folded(value: object) -> object:
    return value.strip().casefold() if isinstance(value, str) else value


def _folded_condition(condition: VectorFilterCondition) -> VectorFilterCondition:
    """Fold a ``facet.*`` condition's text the way ``facet_filter_from_mapping`` does."""
    value = condition.value
    folded = (
        [_folded(item) for item in value] if isinstance(value, list | tuple) else _folded(value)
    )
    return condition.model_copy(update={"value": folded})


@dataclass(frozen=True)
class EntityHit:
    """One ranked entity point, for routing and not yet cleared to be shown.

    Attributes:
        node_key: Graph node key of the source entity the point summarises.
        source_scope_id: Source scope of the entity, or None when unrecorded.
        score: Similarity of the point to the query vector.
        coverage_mode: How much of the entity the summary covers, or None when unrecorded.
    """

    node_key: str
    source_scope_id: str | None
    score: float
    coverage_mode: str | None


@dataclass(frozen=True, slots=True)
class _ReleasedHit:
    """A ranked hit with the card and evidence the authority released for it.

    Attributes:
        hit: The ranked entity point.
        card: The released summary card.
        coverage_mode: How much of the entity the released view covers.
        chunks: Released evidence chunk ids, best first.
    """

    hit: EntityHit
    card: SummaryCard
    coverage_mode: str | None
    chunks: tuple[str, ...]


def split_facet_filters(
    filters: VectorFilter | None,
) -> tuple[VectorFilter | None, VectorFilter | None]:
    """Separate ``facet.*`` conditions from the ones meant for evidence payloads.

    Facets live on entity summary points and everything else on chunks, so one
    filter has to be routed to two searches. Facet text is case-folded as it was
    stored, so it matches here exactly as it does in ``find_entities``.

    Args:
        filters: The caller's filter, or None.

    Returns:
        ``(facet_filter, remaining_filter)``, each None when it has no conditions.
    """
    if filters is None:
        return None, None
    facet: dict[str, list[VectorFilterCondition]] = {"must": [], "should": [], "must_not": []}
    rest: dict[str, list[VectorFilterCondition]] = {"must": [], "should": [], "must_not": []}
    for clause in facet:
        for condition in getattr(filters, clause):
            if condition.field.startswith(FACET_FILTER_PREFIX):
                facet[clause].append(_folded_condition(condition))
            else:
                rest[clause].append(condition)
    return (
        VectorFilter(**facet) if any(facet.values()) else None,
        VectorFilter(**rest) if any(rest.values()) else None,
    )


@dataclass(frozen=True)
class EntitySummarySearch:
    """Search accepted source-entity cards and return the evidence behind them.

    Attributes:
        summaries: Summary authority that releases cards and evidence per caller.
        vectors: Vector repository holding the entity index and evidence points.
        profile: Index profile naming the entity index and its embedding.
        max_entities: Entities ranked without a facet filter, unless a limit is given.
        max_chunks_per_entity: Evidence chunks taken from each entity.
        entity_weight: Fusion weight of entity-reached evidence against chunk candidates.
        rrf_constant: Reciprocal-rank-fusion constant.
    """

    summaries: SummaryReaderPort
    vectors: VectorRepositoryPort
    profile: ContextualIndexProfile
    max_entities: int = _MAX_ENTITIES
    max_chunks_per_entity: int = _MAX_CHUNKS_PER_ENTITY
    entity_weight: float = 0.3
    rrf_constant: int = 60

    async def expand(
        self,
        candidates: tuple[VectorSearchResult, ...],
        dense_vector: tuple[float, ...] | None,
        *,
        context: StorageOperationContext,
        facet_filter: VectorFilter | None = None,
        chunk_filter: VectorFilter | None = None,
    ) -> tuple[VectorSearchResult, ...]:
        """Fuse entity-reached evidence into the candidates, or replace them.

        Without ``facet_filter``, evidence from the top-ranked entities joins the
        candidates by rank fusion. With it, only evidence from qualifying entities
        is returned. When no evidence is reached, enrichment returns the
        candidates unchanged and selection returns nothing.

        Args:
            candidates: Candidates from chunk search, best first.
            dense_vector: Query embedding, or None when the query has none.
            context: Storage context of the caller's request.
            facet_filter: ``facet.*`` conditions that select entities, or None to enrich.
            chunk_filter: The caller's other conditions. Reached evidence must meet
                them too, and their scope conditions also narrow the entity ranking.

        Returns:
            The fused candidates, or the selected evidence when ``facet_filter`` is set.
        """
        if dense_vector is None or len(dense_vector) != self.profile.dimension:
            return candidates if facet_filter is None else ()
        node_keys = await self.matching_entities(
            dense_vector,
            context,
            _with_scope_conditions(facet_filter, chunk_filter),
            limit=_MAX_SELECTED_ENTITIES if facet_filter is not None else self.max_entities,
        )
        reached = tuple(
            item
            for item in await self._evidence_for(node_keys, context)
            if chunk_filter is None or payload_matches(item.payload, chunk_filter)
        )
        if facet_filter is not None:
            return reached
        if not reached:
            return candidates
        return fuse_candidates(
            candidates,
            reached,
            semantic_weight=self.entity_weight,
            rrf_constant=self.rrf_constant,
        )

    async def matching_entities(
        self,
        dense_vector: tuple[float, ...],
        context: StorageOperationContext,
        facet_filter: VectorFilter | None = None,
        *,
        limit: int | None = None,
    ) -> tuple[str, ...]:
        """Rank entity node keys by similarity, within the facet filter if any."""
        return tuple(
            hit.node_key
            for hit in await self.ranked_entities(dense_vector, context, facet_filter, limit=limit)
        )

    async def ranked_entities(
        self,
        dense_vector: tuple[float, ...],
        context: StorageOperationContext,
        facet_filter: VectorFilter | None = None,
        *,
        limit: int | None = None,
    ) -> tuple[EntityHit, ...]:
        """Rank entity points by similarity, within the facet filter if any.

        The hits are routing data only. The summary authority decides, per request,
        whether any of them may be shown. A missing entity index ranks nothing.
        """
        return await self._rank(dense_vector, context, facet_filter, limit=limit) or ()

    async def find(
        self,
        request: EntityFindRequest,
        request_id: str,
        dense_vector: tuple[float, ...],
        context: StorageOperationContext,
    ) -> EntityFindResponse:
        """Rank entity points and return the matches the summary authority releases.

        Hits the authority withholds are counted only on a tenant-shared corpus.
        Under source ACLs they stay silent, because a count would reveal how many
        hidden entities match. There the answer is marked truncated only when more
        than ``limit`` hits were released, so it may omit visible matches ranked
        further down without saying so.

        Args:
            request: The caller's access, query, facets, source scopes and limit.
            request_id: Identifier echoed on the response.
            dense_vector: Query embedding, in the entity index's dimension.
            context: Storage context the entity index is searched under.

        Returns:
            At most ``request.limit`` released matches in rank order, with the
            truncation flag, reason codes such as a missing entity index and, on a
            tenant-shared corpus, the number of withheld hits.
        """
        facet_filter = facet_filter_from_mapping(request.facets, request.source_scope_ids)
        hits = await self._rank(dense_vector, context, facet_filter, limit=request.limit + 1)
        if hits is None:
            return EntityFindResponse(request_id, (), reasons=(ENTITY_INDEX_UNAVAILABLE,))
        if not hits:
            unknown = await self._undeclared_facets(request.facets, context)
            return EntityFindResponse(request_id, (), reasons=(UNKNOWN_FACET,) if unknown else ())
        released, withheld = await self._released(request, hits)
        matches = tuple(
            self._match(item, rank=rank)
            for rank, item in enumerate(released[: request.limit], start=1)
        )
        tenant_shared = request.access.corpus_mode == "tenant_shared"
        truncated = (len(hits) if tenant_shared else len(released)) > request.limit
        if not withheld or not tenant_shared:
            return EntityFindResponse(request_id, matches, truncated=truncated)
        return EntityFindResponse(
            request_id,
            matches,
            truncated=truncated,
            reasons=(ENTITIES_WITHOUT_RELEASED_EVIDENCE,),
            withheld_count=withheld,
        )

    async def _released(
        self, request: EntityFindRequest, hits: tuple[EntityHit, ...]
    ) -> tuple[list[_ReleasedHit], int]:
        """Return the hits the authority releases, and how many it withheld.

        Every ranked hit is checked, so the released count is known past ``limit``.
        A withheld hit is counted only while fewer than ``limit`` hits were
        released, because the answer stops at the ``limit``-th match.
        """
        tenant_id = str(request.access.tenant_id)
        keys = tuple(hit.node_key for hit in hits)
        evidence, views = await asyncio.gather(
            self.summaries.entity_evidence(tenant_id, keys, access=request.access),
            self.summaries.views(tenant_id, keys, access=request.access),
        )
        released: list[_ReleasedHit] = []
        withheld = 0
        for hit in hits:
            item = _released_hit(hit, evidence.get(hit.node_key), views.get(hit.node_key))
            if item is not None:
                released.append(item)
            elif len(released) < request.limit:
                withheld += 1
        return released, withheld

    def _match(self, released: _ReleasedHit, *, rank: int) -> EntityMatch:
        card = released.card
        return EntityMatch(
            node_key=released.hit.node_key,
            source_scope_id=released.hit.source_scope_id,
            rank=rank,
            score=released.hit.score,
            description=card.description,
            coverage_mode=released.coverage_mode,
            attributes=tuple(
                {
                    "name": item.name,
                    "values": list(item.values),
                    "from_document_ids": list(item.from_document_ids),
                }
                for item in card.attributes
            ),
            evidence_chunk_ids=released.chunks[: self.max_chunks_per_entity],
        )

    async def _undeclared_facets(
        self, facets: Mapping[str, object], context: StorageOperationContext
    ) -> tuple[str, ...]:
        """Return the facet names the entity index has no payload index for.

        Every declared facet is indexed when its cards are published, so a missing
        name was declared by no scope. The cached index list is refreshed once
        before a name is reported.
        """
        if not facets or not isinstance(self.vectors, PayloadIndexCatalog):
            return ()
        index = self.profile.entity_index_name
        wanted = {f"{FACET_FILTER_PREFIX}{name}" for name in facets}
        indexed = await self.vectors.indexed_payload_fields(index, context=context)
        if not wanted <= indexed:
            indexed = await self.vectors.indexed_payload_fields(
                index, refresh=True, context=context
            )
        return tuple(sorted(wanted - indexed))

    async def _rank(
        self,
        dense_vector: tuple[float, ...],
        context: StorageOperationContext,
        facet_filter: VectorFilter | None,
        *,
        limit: int | None,
    ) -> tuple[EntityHit, ...] | None:
        """Rank entity hits, or return None when the tenant has no entity index."""
        index = self.profile.entity_index_name
        if not await self.vectors.index_exists(index, context=context):
            return None
        filters = VectorFilter(
            must=[
                VectorFilterCondition(
                    field="embedding_profile", value=self.profile.entity_fingerprint
                ),
                *(facet_filter.must if facet_filter else []),
            ],
            should=list(facet_filter.should) if facet_filter else [],
            must_not=list(facet_filter.must_not) if facet_filter else [],
        )
        hits = await self.vectors.search(
            VectorSearchQuery(
                index_name=index,
                vector=list(dense_vector),
                top_k=limit
                or (_MAX_SELECTED_ENTITIES if facet_filter is not None else self.max_entities),
                filters=filters,
            ),
            context=context,
        )
        ranked: dict[str, EntityHit] = {}
        for hit in hits:
            payload = hit.payload
            key = payload.get("node_key")
            if (
                payload.get("record_kind") != ENTITY_SUMMARY_RECORD_KIND
                or payload.get("projection_point_id") != hit.id
                or not isinstance(key, str)
                or key in ranked
            ):
                continue
            scope = payload.get("source_scope_id")
            coverage = payload.get("coverage_mode")
            ranked[key] = EntityHit(
                key,
                scope if isinstance(scope, str) else None,
                float(hit.score),
                coverage if isinstance(coverage, str) else None,
            )
        return tuple(ranked.values())

    async def _evidence_for(
        self,
        node_keys: tuple[str, ...],
        context: StorageOperationContext,
    ) -> tuple[VectorSearchResult, ...]:
        """Load each entity's released evidence chunks, in entity rank order.

        Every score is zero, because a chunk's position comes from its entity's
        rank, not from its own similarity.
        """
        if not node_keys:
            return ()
        evidence = await self.summaries.entity_evidence(
            str(context.tenant_id), node_keys, access=context.access
        )
        identity = DocumentIdentityBuilder()
        chunks = tuple(
            dict.fromkeys(
                chunk
                for key in node_keys
                for chunk in evidence.get(key, ())[: self.max_chunks_per_entity]
            )
        )
        if not chunks:
            return ()
        records = await self.vectors.get_records(
            "evidence",
            tuple(identity.point_id(chunk_id=chunk) for chunk in chunks),
            context=context,
        )
        by_point = {
            row.id: row
            for row in records
            if str(row.tenant_id) == str(context.tenant_id)
            and row.payload.get("record_kind") == "evidence"
            and row.payload.get("chunk_id") in set(chunks)
        }
        return tuple(
            VectorSearchResult(id=row.id, score=0, raw_score=0, payload=row.payload)
            for chunk in chunks
            if (row := by_point.get(identity.point_id(chunk_id=chunk))) is not None
        )


def _released_hit(
    hit: EntityHit, chunks: tuple[str, ...] | None, view: SummaryView | None
) -> _ReleasedHit | None:
    """Pair a hit with its released card and evidence, or None when either is withheld."""
    if not chunks or view is None or view.card is None:
        return None
    return _ReleasedHit(hit, view.card, view.coverage_mode, chunks)


def _with_scope_conditions(
    facet_filter: VectorFilter | None, chunk_filter: VectorFilter | None
) -> VectorFilter | None:
    """Carry the caller's ``source_scope_id`` conditions onto the entity search.

    Entity points carry their scope, so ranking within the caller's scopes keeps
    entities of other scopes from taking every ranked place.
    """

    def scoped(conditions: list[VectorFilterCondition]) -> list[VectorFilterCondition]:
        return [
            item
            for item in conditions
            if item.field == "source_scope_id"
            and item.operator in {FilterOperator.EQUALS, FilterOperator.IN}
        ]

    if chunk_filter is None:
        return facet_filter
    must, must_not = scoped(chunk_filter.must), scoped(chunk_filter.must_not)
    if not must and not must_not:
        return facet_filter
    base = facet_filter or VectorFilter()
    return VectorFilter(
        must=[*base.must, *must], should=list(base.should), must_not=[*base.must_not, *must_not]
    )


def payload_matches(payload: Mapping[str, object], filters: VectorFilter) -> bool:
    """Return whether an evidence payload satisfies a filter, as Qdrant reads it.

    Entity-reached chunks are fetched by id, not searched, so the caller's filter
    is checked here instead. A dotted field walks nested objects, a list-valued
    field matches when any member does, and ``should`` needs one of its
    conditions when it has any. An operator this cannot evaluate fails closed.
    """
    return (
        all(_condition_matches(payload, item) for item in filters.must)
        and (not filters.should or any(_condition_matches(payload, i) for i in filters.should))
        and not any(_condition_matches(payload, item) for item in filters.must_not)
    )


_COMPARISONS = {
    FilterOperator.GREATER_THAN: lambda value, bound: value > bound,
    FilterOperator.GREATER_THAN_OR_EQUAL: lambda value, bound: value >= bound,
    FilterOperator.LESS_THAN: lambda value, bound: value < bound,
    FilterOperator.LESS_THAN_OR_EQUAL: lambda value, bound: value <= bound,
}


def _condition_matches(payload: Mapping[str, object], condition: VectorFilterCondition) -> bool:
    values = _payload_values(payload, condition.field)
    operator, wanted = condition.operator, condition.value
    if operator == FilterOperator.EXISTS:
        return bool(values) is (wanted is not False)
    if operator in {FilterOperator.EQUALS, FilterOperator.NOT_EQUALS}:
        found = any(_same(value, wanted) for value in values)
        return found if operator == FilterOperator.EQUALS else not found
    if operator in {FilterOperator.IN, FilterOperator.NOT_IN}:
        options = wanted if isinstance(wanted, list | tuple) else ()
        found = any(_same(value, option) for value in values for option in options)
        return found if operator == FilterOperator.IN else not found
    compare = _COMPARISONS.get(operator)
    if compare is None or not _is_number(wanted):
        return False
    return any(_is_number(value) and compare(value, wanted) for value in values)


def _payload_values(payload: Mapping[str, object], field: str) -> tuple[object, ...]:
    value: object = payload
    for part in field.split("."):
        if not isinstance(value, Mapping):
            return ()
        value = value.get(part)
    if value is None:
        return ()
    return tuple(value) if isinstance(value, list | tuple) else (value,)


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _same(value: object, wanted: object) -> bool:
    """Compare payload values without treating a bool as equal to a number."""
    if isinstance(value, bool) or isinstance(wanted, bool):
        return isinstance(value, bool) and isinstance(wanted, bool) and value is wanted
    return value == wanted
