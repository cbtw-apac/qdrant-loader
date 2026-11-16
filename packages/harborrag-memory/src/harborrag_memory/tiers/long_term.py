"""Long-term memory tier that authorizes callers over the canonical repository.

A write must be visible to its caller and attributed only to identities the
caller holds, and a query runs only as the caller. GLOBAL memories are readable
here but never written or deleted. Storage and visibility filtering stay in the
repository.

Typical usage example:

    tier = LongTermMemory(repository)
    await tier.save(caller, memory)
    memories = await tier.search(caller, MemoryQuery(owner=caller))
"""

from __future__ import annotations

from dataclasses import fields

from harborrag_core.ports.memory import (
    Memory,
    MemoryOwner,
    MemoryQuery,
    MemoryRepository,
    MemoryScope,
    visible_to,
)

from ..errors import MemoryScopeError


class LongTermMemory:
    """Facade over the canonical long-term memory repository.

    Writes, queries and deletes are authorized for the caller before they reach
    the repository.

    Args:
        repository: Canonical store the memories are saved to, read from and deleted from.
    """

    def __init__(self, repository: MemoryRepository) -> None:
        self._repository = repository

    async def save(self, caller: MemoryOwner, memory: Memory) -> None:
        """Store ``memory`` on behalf of ``caller``.

        Raises ``MemoryScopeError`` when the memory is GLOBAL, is not visible to
        ``caller``, or is attributed to an identity ``caller`` does not hold.

        Args:
            caller: The authenticated owner making the write.
            memory: The memory to store.
        """
        _authorize_write(caller, memory)
        await self._repository.save(memory)

    async def remember(self, caller: MemoryOwner, memory: Memory) -> None:
        """Store ``memory`` on behalf of ``caller``, as :meth:`save` does."""
        await self.save(caller, memory)

    async def get(self, caller: MemoryOwner, memory_id: str) -> Memory | None:
        """Return the memory with ``memory_id`` when ``caller`` can see it, else None."""
        return await self._repository.get(caller, memory_id)

    async def search(self, caller: MemoryOwner, query: MemoryQuery) -> tuple[Memory, ...]:
        """Search the memories visible to ``caller``.

        Raises ``MemoryScopeError`` when ``query`` is issued as another owner.

        Args:
            caller: The authenticated owner searching.
            query: The search, whose owner must be ``caller``.

        Returns:
            The matching memories, in the repository's order.
        """
        _require_same_owner(caller, query.owner)
        return await self._repository.search(query)

    async def delete(self, caller: MemoryOwner, memory_id: str) -> None:
        """Delete the memory with ``memory_id`` when ``caller`` can see it.

        An unknown id, or one ``caller`` cannot see, is a silent no-op.

        Args:
            caller: The authenticated owner asking for the delete.
            memory_id: The memory to delete.

        Raises:
            MemoryScopeError: The memory is GLOBAL. Deleting one takes an
                administrative capability.
        """
        memory = await self._repository.get(caller, memory_id)
        if memory is not None and memory.scope is MemoryScope.GLOBAL:
            raise MemoryScopeError("global memory deletes require an administrative capability")
        await self._repository.delete(caller, memory_id)

    async def forget(self, caller: MemoryOwner, memory_id: str) -> None:
        """Delete ``memory_id`` for ``caller``, as :meth:`delete` does."""
        await self.delete(caller, memory_id)


def _authorize_write(caller: MemoryOwner, memory: Memory) -> None:
    if memory.scope is MemoryScope.GLOBAL:
        raise MemoryScopeError("global memory writes require an administrative capability")
    if caller.tenant_id != memory.owner.tenant_id or not visible_to(
        memory.scope, memory.owner, caller
    ):
        raise MemoryScopeError("caller is not authorized to write memory for this owner")
    _reject_borrowed_identity(caller, memory.owner)


def _reject_borrowed_identity(caller: MemoryOwner, owner: MemoryOwner) -> None:
    """Refuse a write attributed to an identity the caller does not hold.

    ``visible_to`` checks only the fields the scope keys on, so without this a
    TENANT write could carry a colleague's ``user_id``. Erasure is by owner, so the
    row would go with the colleague's erasure and be missed by the author's. A
    field may still be left unset, which is how a tenant-wide fact is recorded.
    """
    borrowed = sorted(
        field.name
        for field in fields(MemoryOwner)
        if field.name != "tenant_id"
        and getattr(owner, field.name) is not None
        and getattr(owner, field.name) != getattr(caller, field.name)
    )
    if borrowed:
        raise MemoryScopeError(
            "caller cannot write memory attributed to another owner: " + ", ".join(borrowed)
        )


def _require_same_owner(caller: MemoryOwner, requested: MemoryOwner) -> None:
    if caller != requested:
        raise MemoryScopeError("memory query owner must match the authenticated caller")
