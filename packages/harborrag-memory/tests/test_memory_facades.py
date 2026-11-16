from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from harborrag_core.contracts.errors import HarborConfigurationError, HarborSecurityError
from harborrag_core.ports.conversation import ConversationIdentity, ConversationTurn
from harborrag_core.ports.memory import (
    Memory,
    MemoryOwner,
    MemoryQuery,
    MemoryScope,
    MemoryType,
    visible_to,
)
from harborrag_memory import (
    LongTermMemory,
    MemoryConfigurationError,
    MemoryManager,
    MemoryManagerConfig,
    MemoryScopeError,
    ShortTermMemory,
)

pytestmark = pytest.mark.unit


@dataclass
class ConversationRepositoryFake:
    values: dict[ConversationIdentity, tuple[ConversationTurn, ...]] = field(default_factory=dict)

    async def create(self, identity: ConversationIdentity, *, kind: str = "chat") -> None:
        del kind
        self.values.setdefault(identity, ())

    async def exists(self, identity: ConversationIdentity, *, kind: str | None = None) -> bool:
        del kind
        return identity in self.values

    async def recent(
        self, identity: ConversationIdentity, *, limit: int = 2
    ) -> tuple[ConversationTurn, ...]:
        return self.values.get(identity, ())[-limit:]

    async def append(self, identity: ConversationIdentity, turn: ConversationTurn) -> None:
        self.values[identity] = (*self.values.get(identity, ()), turn)

    async def clear(self, identity: ConversationIdentity) -> None:
        self.values[identity] = ()


@dataclass
class MemoryRepositoryFake:
    values: dict[str, Memory] = field(default_factory=dict)

    async def save(self, memory: Memory) -> None:
        self.values[memory.memory_id] = memory

    async def get(self, caller: MemoryOwner, memory_id: str) -> Memory | None:
        memory = self.values.get(memory_id)
        if memory is None or not visible_to(memory.scope, memory.owner, caller):
            return None
        return memory

    async def search(self, query: MemoryQuery) -> tuple[Memory, ...]:
        return tuple(
            memory
            for memory in self.values.values()
            if visible_to(memory.scope, memory.owner, query.owner)
        )[: query.limit]

    async def delete(self, caller: MemoryOwner, memory_id: str) -> None:
        if await self.get(caller, memory_id) is not None:
            self.values.pop(memory_id, None)


@pytest.fixture
def owner() -> MemoryOwner:
    return MemoryOwner(
        tenant_id="tenant-a",
        user_id="user-1",
        principal_id="user-1",
        session_id="session-1",
    )


def make_memory(owner: MemoryOwner, *, memory_id: str = "memory-1") -> Memory:
    return Memory(
        memory_id=memory_id,
        scope=MemoryScope.USER,
        memory_type=MemoryType.FACT,
        owner=owner,
        content="Remember this",
    )


def test_config_rejects_invalid_bounds() -> None:
    with pytest.raises(ValueError, match="recent_turn_limit"):
        MemoryManagerConfig(recent_turn_limit=0)


@pytest.mark.asyncio
async def test_short_term_uses_conversation_turns_and_validates_owner(
    owner: MemoryOwner,
) -> None:
    tier = ShortTermMemory(ConversationRepositoryFake())
    turn = ConversationTurn(user_content="question", assistant_content="answer")
    await tier.append(owner, turn)
    await tier.append(owner, turn)
    assert await tier.recent(owner) == (turn, turn)
    await tier.clear(owner)
    assert await tier.recent(owner) == ()

    with pytest.raises(MemoryScopeError, match="principal_id and session_id"):
        await tier.recent(MemoryOwner(tenant_id="tenant-a"))


@pytest.mark.asyncio
async def test_long_term_refuses_a_write_attributed_to_a_colleague(
    owner: MemoryOwner,
) -> None:
    """Attribution inside a tenant has to be the caller's own.

    ``visible_to`` checks only the fields the scope keys on, so a TENANT write
    was checked against the tenant alone. Erasure is by owner, so a borrowed
    ``user_id`` would put the row in the colleague's erasure, not the author's.
    """
    tier = LongTermMemory(MemoryRepositoryFake())
    colleague = Memory(
        memory_id="borrowed-1",
        scope=MemoryScope.TENANT,
        memory_type=MemoryType.FACT,
        owner=MemoryOwner(tenant_id=owner.tenant_id, user_id="someone-else"),
        content="the company is metric",
    )

    with pytest.raises(MemoryScopeError, match="attributed to another owner"):
        await tier.save(owner, colleague)


@pytest.mark.asyncio
async def test_long_term_still_accepts_an_unattributed_tenant_fact(
    owner: MemoryOwner,
) -> None:
    """Leaving a field unset is how a genuinely tenant-wide fact is recorded."""
    repository = MemoryRepositoryFake()
    tier = LongTermMemory(repository)
    tenant_wide = Memory(
        memory_id="tenant-1",
        scope=MemoryScope.TENANT,
        memory_type=MemoryType.FACT,
        owner=MemoryOwner(tenant_id=owner.tenant_id),
        content="the company is metric",
    )

    await tier.save(owner, tenant_wide)

    assert await tier.get(owner, "tenant-1") == tenant_wide


@pytest.mark.asyncio
async def test_long_term_rejects_forged_and_global_writes(owner: MemoryOwner) -> None:
    repository = MemoryRepositoryFake()
    tier = LongTermMemory(repository)
    memory = make_memory(owner)
    attacker = MemoryOwner(
        tenant_id="tenant-b",
        user_id=owner.user_id,
        principal_id=owner.principal_id,
        session_id=owner.session_id,
    )
    with pytest.raises(MemoryScopeError, match="not authorized"):
        await tier.save(attacker, memory)
    global_memory = Memory(
        memory_id="global-1",
        scope=MemoryScope.GLOBAL,
        memory_type=MemoryType.FACT,
        owner=owner,
        content="global",
    )
    with pytest.raises(MemoryScopeError, match="administrative"):
        await tier.save(owner, global_memory)

    await tier.remember(owner, memory)
    assert await tier.get(owner, memory.memory_id) == memory
    with pytest.raises(MemoryScopeError, match="authenticated caller"):
        await tier.search(attacker, MemoryQuery(owner=owner))
    assert await tier.search(owner, MemoryQuery(owner=owner)) == (memory,)
    await tier.forget(owner, memory.memory_id)
    assert await tier.get(owner, memory.memory_id) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("caller_tenant", ["tenant-a", "tenant-b"])
async def test_long_term_delete_of_a_global_memory_raises_and_keeps_the_row(
    owner: MemoryOwner, caller_tenant: str
) -> None:
    """A global memory is readable by every caller, so deleting one takes an admin.

    The row is placed in the repository directly because ``save`` already
    refuses global writes. The caller from another tenant sees it too.
    """
    repository = MemoryRepositoryFake()
    global_memory = Memory(
        memory_id="global-1",
        scope=MemoryScope.GLOBAL,
        memory_type=MemoryType.FACT,
        owner=MemoryOwner(tenant_id=owner.tenant_id),
        content="global",
    )
    repository.values[global_memory.memory_id] = global_memory
    tier = LongTermMemory(repository)
    caller = MemoryOwner(tenant_id=caller_tenant, user_id="user-2", principal_id="user-2")

    with pytest.raises(MemoryScopeError, match="administrative"):
        await tier.delete(caller, global_memory.memory_id)
    with pytest.raises(MemoryScopeError, match="administrative"):
        await tier.forget(caller, global_memory.memory_id)

    assert repository.values == {global_memory.memory_id: global_memory}


@pytest.mark.asyncio
async def test_long_term_delete_of_a_user_memory_or_unknown_id_succeeds(
    owner: MemoryOwner,
) -> None:
    repository = MemoryRepositoryFake()
    tier = LongTermMemory(repository)
    memory = make_memory(owner)
    await tier.save(owner, memory)

    await tier.delete(owner, memory.memory_id)
    await tier.delete(owner, "missing-1")

    assert repository.values == {}


@pytest.mark.asyncio
async def test_manager_delegates_and_builds_a_snapshot(owner: MemoryOwner) -> None:
    conversation = ConversationRepositoryFake()
    short = ShortTermMemory(conversation)
    repository = MemoryRepositoryFake()
    long = LongTermMemory(repository)
    manager = MemoryManager(short, long)
    turn = ConversationTurn(user_content="question", assistant_content="answer")
    memory = make_memory(owner)
    await manager.append(owner, turn)
    await manager.save(owner, memory)

    snapshot = await manager.snapshot(owner, query=MemoryQuery(owner=owner))
    assert snapshot.recent_turns == (turn,)
    assert snapshot.memories == (memory,)


@pytest.mark.asyncio
async def test_manager_rejects_missing_tiers_and_mismatched_snapshot_owner(
    owner: MemoryOwner,
) -> None:
    manager = MemoryManager()
    with pytest.raises(MemoryConfigurationError, match="short-term"):
        await manager.recent(owner)
    assert isinstance(MemoryConfigurationError("missing"), HarborConfigurationError)
    assert isinstance(MemoryScopeError("denied"), HarborSecurityError)

    other = MemoryOwner(tenant_id="tenant-b", principal_id="other")
    with pytest.raises(MemoryScopeError, match="snapshot query owner"):
        await manager.snapshot(owner, query=MemoryQuery(owner=other))
