"""Who may delete a memory, and erasure that recovers from partial failures."""

from __future__ import annotations

from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app_test_memory import FakeMemoryIndex, FakeMemoryStore, memory

from harborrag_app.workflow_control.control_plane.effect_recovery import (
    recover_pending_control_plane_effects,
)
from harborrag_app.workflow_control.memory.administration import MemoryAdministrationService
from harborrag_core.contracts.errors import HarborAuthError
from harborrag_core.domain.pending_effect import PendingControlPlaneEffect
from harborrag_core.ports.conversation import ConversationIdentity
from harborrag_core.ports.memory import MemoryOwner, MemoryScope
from harborrag_core.testing.control_plane_fakes import FakePendingEffectRepository
from harborrag_runtime.memory import InMemoryConversationMemory

pytestmark = pytest.mark.unit


@pytest.fixture
def stores() -> SimpleNamespace:
    return SimpleNamespace(
        memories=FakeMemoryStore(),
        index=FakeMemoryIndex(),
        conversations=InMemoryConversationMemory(),
        pending_effects=FakePendingEffectRepository(),
    )


def administration(stores: SimpleNamespace, *, journal: bool = True) -> MemoryAdministrationService:
    return MemoryAdministrationService(
        conversations=stores.conversations,
        memories=stores.memories,
        index=stores.index,
        pending_effects=stores.pending_effects if journal else None,
    )


async def recover(stores: SimpleNamespace) -> int:
    """Replay pending erasures through a new service, as recovery after a restart does."""
    return await recover_pending_control_plane_effects(
        stores, erasure_handler=administration(stores).recover_erasure
    )


@pytest.mark.asyncio
async def test_vector_failure_recovers_after_canonical_row_is_gone(
    stores: SimpleNamespace,
) -> None:
    row = memory("memory-1")
    await stores.memories.save(row)
    stores.index.failure = RuntimeError("index unavailable")
    await administration(stores).delete_memory(row.owner, row.memory_id)
    assert not stores.memories.rows
    assert len(stores.pending_effects.effects) == 1
    assert await recover(stores) == 0
    stores.index.failure = None
    assert await recover(stores) == 1
    assert stores.index.deleted == [row.memory_id]
    assert not stores.pending_effects.effects


@pytest.mark.asyncio
async def test_session_purge_failure_recovers_without_a_client_retry(
    stores: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = memory("memory-1", scope=MemoryScope.SESSION, session_id="session-1")
    identity = ConversationIdentity(
        row.owner.tenant_id, row.owner.principal_id, row.owner.session_id, row.owner.user_id
    )
    await stores.conversations.create(identity)
    await stores.memories.save(row)
    search = stores.memories.search
    monkeypatch.setattr(stores.memories, "search", AsyncMock(side_effect=RuntimeError("offline")))
    with pytest.raises(RuntimeError, match="offline"):
        await administration(stores).erase_session(row.owner, actor="test")
    assert await stores.conversations.exists(identity)
    assert len(stores.pending_effects.effects) == 1
    monkeypatch.setattr(stores.memories, "search", search)
    assert await recover(stores) == 1
    assert not await stores.conversations.exists(identity)
    assert not stores.memories.rows
    assert stores.index.deleted == [row.memory_id]


@pytest.mark.asyncio
async def test_enqueue_failure_happens_before_deleting_anything(
    stores: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = memory("memory-1")
    await stores.memories.save(row)
    monkeypatch.setattr(
        type(stores.pending_effects), "enqueue", AsyncMock(side_effect=RuntimeError("queue down"))
    )
    with pytest.raises(RuntimeError, match="queue down"):
        await administration(stores).delete_memory(row.owner, row.memory_id)
    assert row.memory_id in stores.memories.rows
    assert not stores.index.deleted


@pytest.mark.asyncio
async def test_canonical_delete_failure_keeps_intent(
    stores: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = memory("memory-1")
    await stores.memories.save(row)
    delete = stores.memories.delete
    monkeypatch.setattr(stores.memories, "delete", AsyncMock(side_effect=RuntimeError("db down")))
    with pytest.raises(RuntimeError, match="db down"):
        await administration(stores).delete_memory(row.owner, row.memory_id)
    assert len(stores.pending_effects.effects) == 1
    monkeypatch.setattr(stores.memories, "delete", delete)
    assert await recover(stores) == 1
    assert not stores.memories.rows
    assert stores.index.deleted == [row.memory_id]


@pytest.mark.asyncio
async def test_without_journal_index_failure_preserves_canonical_retry_handle(
    stores: SimpleNamespace,
) -> None:
    row = memory("memory-1")
    await stores.memories.save(row)
    stores.index.failure = RuntimeError("index down")
    with pytest.raises(RuntimeError, match="index down"):
        await administration(stores, journal=False).delete_memory(row.owner, row.memory_id)
    assert row.memory_id in stores.memories.rows
    stores.index.failure = None
    await administration(stores, journal=False).delete_memory(row.owner, row.memory_id)
    assert not stores.memories.rows


@pytest.mark.asyncio
async def test_recovery_does_not_forget_required_index_after_configuration_change(
    stores: SimpleNamespace,
) -> None:
    row = memory("memory-1")
    await stores.memories.save(row)
    stores.index.failure = RuntimeError("index down")
    await administration(stores).delete_memory(row.owner, row.memory_id)
    stores.index = None
    assert await recover(stores) == 0
    assert len(stores.pending_effects.effects) == 1


@pytest.mark.asyncio
async def test_session_recovery_remains_authorized_when_session_was_already_deleted(
    stores: SimpleNamespace,
) -> None:
    """The durable owner was authorized before deletion.

    A retry must not depend on a conversation row that interrupted cleanup may
    already have removed.
    """
    row = memory("memory-1", scope=MemoryScope.SESSION, session_id="session-1")
    await stores.memories.save(row)
    await stores.pending_effects.enqueue(
        PendingControlPlaneEffect(
            id="interrupted-session-erasure",
            kind="erase_memory_session",
            payload={"owner": asdict(row.owner), "memories_required": True, "index_required": True},
        )
    )
    assert await recover(stores) == 1
    assert not stores.memories.rows
    assert stores.index.deleted == [row.memory_id]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["erase_memory", "erase_memory_session"])
async def test_an_intent_queued_before_the_upgrade_still_recovers(
    stores: SimpleNamespace, kind: str
) -> None:
    row = memory("memory-1", scope=MemoryScope.SESSION, session_id="session-1")
    await stores.memories.save(row)
    await stores.pending_effects.enqueue(
        PendingControlPlaneEffect(
            id="queued-before-0045",
            kind=kind,
            payload={
                "owner": {**asdict(row.owner), "run_id": None},
                "memory_id": row.memory_id,
                "memories_required": True,
                "index_required": True,
            },
        )
    )
    assert await recover(stores) == 1
    assert not stores.memories.rows
    assert stores.index.deleted == [row.memory_id]
    assert not stores.pending_effects.effects


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "shared_scopes", [frozenset(), frozenset(MemoryScope)], ids=["author", "moderator"]
)
async def test_delete_memory_of_a_global_memory_is_forbidden_and_erases_nothing(
    stores: SimpleNamespace, shared_scopes: frozenset[MemoryScope]
) -> None:
    """Neither the author nor a moderator may delete a global memory."""
    row = memory("global-1", scope=MemoryScope.GLOBAL)
    await stores.memories.save(row)

    with pytest.raises(HarborAuthError, match="administrative") as raised:
        await administration(stores).delete_memory(
            row.owner, row.memory_id, shared_scopes=shared_scopes
        )

    assert raised.value.forbidden
    assert row.memory_id in stores.memories.rows
    assert not stores.index.deleted
    assert not stores.pending_effects.effects


@pytest.mark.asyncio
async def test_delete_memory_of_a_colleagues_tenant_memory_needs_authorship_or_moderation(
    stores: SimpleNamespace,
) -> None:
    row = memory("tenant-1", scope=MemoryScope.TENANT, user_id="author-1")
    await stores.memories.save(row)
    colleague = MemoryOwner(
        tenant_id=row.owner.tenant_id, user_id="colleague-1", principal_id="colleague-1"
    )

    with pytest.raises(HarborAuthError, match="only the author") as raised:
        await administration(stores).delete_memory(colleague, row.memory_id)
    assert raised.value.forbidden
    assert row.memory_id in stores.memories.rows

    await administration(stores).delete_memory(
        colleague, row.memory_id, shared_scopes=frozenset({MemoryScope.TENANT})
    )
    assert not stores.memories.rows
    assert stores.index.deleted == [row.memory_id]
