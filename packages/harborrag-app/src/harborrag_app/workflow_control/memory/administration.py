"""Introspection and right-to-erasure over one caller's remembered data.

Erasure spans conversation history, canonical memories and the memory vector
index, which are keyed differently. A user's sessions are found through the
memories they produced, so a session that produced none must be erased through
the session endpoint. No caller deletes a GLOBAL memory here.

Typical usage example:

    service = MemoryAdministrationService(conversations=history, memories=store)
    report = await service.erase_user(owner, actor=admin_id)
"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from harborrag_core.contracts.errors import (
    HarborAuthError,
    HarborNotFoundError,
    HarborUnavailableError,
)
from harborrag_core.domain.pending_effect import PendingControlPlaneEffect
from harborrag_core.ports.control_plane import PendingEffectRepositoryPort
from harborrag_core.ports.conversation import ConversationIdentity
from harborrag_core.ports.memory import MemoryOwner, MemoryQuery, MemoryScope

from .erasure import SESSION_ERASURE, MemoryErasureJournal, stored_owner

if TYPE_CHECKING:
    from harborrag_core.ports.conversation import ConversationHistoryRepository
    from harborrag_core.ports.memory import Memory, MemoryIndex, MemoryRepository

logger = logging.getLogger("harborrag.app.workflow_control.memory.administration")

_PAGE = 1_000
_MAX_PASSES = 50
"""Most pages one purge reads before it stops, 50k memories for one user.

Bounds a purge of a store that keeps growing while it is erased.
"""
_USER_SCOPES = (MemoryScope.USER,)
_SESSION_SCOPES = (MemoryScope.SESSION,)
_AUTHORED_SCOPES = (MemoryScope.PROJECT, MemoryScope.TENANT)
"""Scopes of rows a user authored that a visibility query cannot single out.

PROJECT and TENANT key on fields other than the user, so these rows are matched
on the row's stored user instead.
"""
_SHARED_SCOPES = frozenset({MemoryScope.PROJECT, MemoryScope.TENANT})
"""Scopes whose rows are shared beyond their author.

They are visible to anyone in the tenant (and project) by design, but only the
author -- or a caller granted the scope through ``shared_scopes`` -- may delete
one, and only the author sees its provenance.
"""
_NO_STORE = "long-term memory is not configured for this deployment"


@dataclass(frozen=True, slots=True)
class _Purged:
    """Totals of one purge, plus the conversations its rows came from.

    Attributes:
        memories: Canonical memory rows deleted.
        index_points: Vector index points deleted.
        conversations: ``(principal_id, session_id)`` pairs the deleted rows came from.
    """

    memories: int = 0
    index_points: int = 0
    conversations: frozenset[tuple[str, str]] = frozenset()


@dataclass(frozen=True, slots=True)
class ErasureReport:
    """What one erasure actually removed, per category.

    Attributes:
        memories: Canonical memory rows deleted.
        index_points: Memory vector index points deleted.
        sessions: Conversation sessions the erasure reached.
        conversation_messages_cleared: Sessions whose messages were cleared, not a
            message count.
    """

    memories: int = 0
    index_points: int = 0
    sessions: int = 0
    conversation_messages_cleared: int = 0

    def as_dict(self) -> dict[str, int]:
        """Return the counts keyed by category, as the erasure endpoints report them."""
        return {
            "memories": self.memories,
            "index_points": self.index_points,
            "sessions": self.sessions,
            "conversation_messages_cleared": self.conversation_messages_cleared,
        }


class MemoryAdministrationService:
    """Read and erase the memory of one authenticated caller.

    Args:
        conversations: Conversation history store whose sessions and messages are erased.
        memories: Canonical long-term memory store, or None when the deployment has none.
        index: Vector index over memories, or None when the deployment has none.
        pending_effects: Durable journal of erasure intents, replayed after a
            partial failure. None erases without a journal.
    """

    def __init__(
        self,
        *,
        conversations: ConversationHistoryRepository,
        memories: MemoryRepository | None = None,
        index: MemoryIndex | None = None,
        pending_effects: PendingEffectRepositoryPort | None = None,
    ) -> None:
        self._conversations = conversations
        self._memories = memories
        self._index = index
        self._erasure = MemoryErasureJournal(memories, index, pending_effects)

    def _store(self) -> MemoryRepository:
        if self._memories is None:
            raise HarborUnavailableError(_NO_STORE)
        return self._memories

    async def list_memories(
        self,
        owner: MemoryOwner,
        *,
        scopes: tuple[MemoryScope, ...] = (),
        limit: int = 20,
    ) -> tuple[Memory, ...]:
        """Return the memories visible to ``owner``, newest and most important first.

        Besides the caller's own rows, this includes PROJECT and TENANT rows other
        users authored, which come back without provenance. Facts outside their
        validity window are included, but not expired rows. A deployment without
        a long-term store raises ``HarborUnavailableError``.

        Args:
            owner: The authenticated caller. Its ``project_id`` is the project it
                chose to read.
            scopes: Scopes to return, or empty for every scope.
            limit: Maximum memories to return.

        Returns:
            At most ``limit`` visible memories.
        """
        rows = await self._store().search(
            MemoryQuery(owner=owner, scopes=scopes, limit=limit, include_invalid=True)
        )
        return tuple(
            row
            if _authored_by(row, owner)
            else dataclasses.replace(row, source_session_id=None, source_message_ids=())
            for row in rows
        )

    async def delete_memory(
        self,
        owner: MemoryOwner,
        memory_id: str,
        *,
        shared_scopes: frozenset[MemoryScope] = frozenset(),
    ) -> None:
        """Delete one memory the caller can see, with its vector index point.

        Refusals come before anything is erased or journaled. A deployment without
        a long-term store raises ``HarborUnavailableError``.

        Args:
            owner: The authenticated caller. Visibility and authorship are judged
                against it.
            memory_id: The memory to delete.
            shared_scopes: Shared scopes the caller's role moderates. In them it
                may delete rows other users authored.

        Raises:
            HarborNotFoundError: The memory does not exist or ``owner`` cannot see it.
            HarborAuthError: The memory is GLOBAL, or is a PROJECT or TENANT row
                ``owner`` neither authored nor moderates. The error is ``forbidden``.
        """
        store = self._store()
        memory = await store.get(owner, memory_id)
        if memory is None:
            raise HarborNotFoundError("Memory was not found")
        if memory.scope is MemoryScope.GLOBAL:
            raise HarborAuthError(
                "global memory deletes require an administrative capability", forbidden=True
            )
        if (
            memory.scope in _SHARED_SCOPES
            and memory.scope not in shared_scopes
            and not _authored_by(memory, owner)
        ):
            raise HarborAuthError(
                f"only the author may delete this {memory.scope.value} memory", forbidden=True
            )
        await self._erasure.erase_memory(memory)
        logger.info(
            "Memory deleted tenant=%s actor=%s memory_id=%s scope=%s",
            owner.tenant_id,
            owner.principal_id,
            memory_id,
            memory.scope.value,
        )

    async def erase_session(self, owner: MemoryOwner, *, actor: str) -> ErasureReport:
        """Erase one session with its messages, session memories and their vectors.

        The session itself is deleted, so it leaves the caller's conversation list.
        When a journal is configured, the intent is recorded first, so recovery
        finishes an erasure that fails partway.

        Args:
            owner: The caller, naming the principal and session to erase.
            actor: Who asked for the erasure, recorded in the log.

        Returns:
            What the erasure removed.

        Raises:
            HarborNotFoundError: ``owner`` names no session, or the session does not
                exist.
        """
        if owner.session_id is None or owner.principal_id is None:
            raise HarborNotFoundError("Conversation session was not found")
        identity = ConversationIdentity(
            owner.tenant_id,
            owner.principal_id,
            owner.session_id,
            owner.user_id or owner.principal_id,
        )
        if not await self._conversations.exists(identity):
            raise HarborNotFoundError("Conversation session was not found")
        effect_id = await self._erasure.begin(
            SESSION_ERASURE,
            owner,
            memories_required=self._memories is not None,
            index_required=self._index is not None,
        )
        purged = await self._purge(owner, _SESSION_SCOPES)
        await self._conversations.delete(identity)
        await self._erasure.complete(effect_id)
        report = ErasureReport(
            memories=purged.memories,
            index_points=purged.index_points,
            sessions=1,
            conversation_messages_cleared=1,
        )
        _log_erasure("session", owner.tenant_id, actor, owner.session_id, report)
        return report

    async def recover_erasure(self, effect: PendingControlPlaneEffect) -> bool:
        """Replay an erasure intent that a partial failure left pending.

        The intent's stored owner was authorized when it was queued, so the replay
        works even after the session or canonical row is gone.

        Args:
            effect: A pending control-plane effect of any kind.

        Returns:
            True when the effect was an erasure intent and was replayed, False when
            it is another kind of effect.

        Raises:
            HarborUnavailableError: A store the intent requires is not configured.
        """
        if await self._erasure.replay(effect):
            return True
        if effect.kind != SESSION_ERASURE:
            return False
        owner = stored_owner(effect.payload["owner"])
        if effect.payload.get("memories_required") and self._memories is None:
            raise HarborUnavailableError("session erasure memory store is not configured")
        if effect.payload.get("index_required") and self._index is None:
            raise HarborUnavailableError("session erasure index is not configured")
        if owner.principal_id is None or owner.session_id is None:
            raise ValueError("session erasure intent lacks its ownership key")
        await self._purge(owner, _SESSION_SCOPES)
        await self._conversations.delete(
            ConversationIdentity(
                owner.tenant_id,
                owner.principal_id,
                owner.session_id,
                owner.user_id or owner.principal_id,
            )
        )
        return True

    async def erase_user(self, owner: MemoryOwner, *, actor: str) -> ErasureReport:
        """Erase everything reachable for one end user within the tenant.

        User-scoped memories are purged first, and the sessions they came from
        then lose their messages and session memories. A last pass erases PROJECT
        and TENANT rows the user authored, which no visibility query reaches.

        Args:
            owner: The caller, naming the tenant and the end user to erase.
            actor: Who asked for the erasure, recorded in the log.

        Returns:
            What the erasure removed.

        Raises:
            HarborNotFoundError: ``owner`` names no end user.
        """
        target = owner.user_id
        if target is None:
            raise HarborNotFoundError("User was not found")
        user_owner = MemoryOwner(tenant_id=owner.tenant_id, user_id=target)
        purged = await self._purge(user_owner, _USER_SCOPES)
        memories = purged.memories
        points = purged.index_points
        for principal_id, session_id in sorted(purged.conversations):
            session_owner = MemoryOwner(
                tenant_id=owner.tenant_id,
                user_id=target,
                principal_id=principal_id,
                session_id=session_id,
            )
            session_purge = await self._purge(session_owner, _SESSION_SCOPES)
            memories += session_purge.memories
            points += session_purge.index_points
            await self._conversations.clear_messages(
                ConversationIdentity(owner.tenant_id, principal_id, session_id, target)
            )
        authored = await self._purge(user_owner, _AUTHORED_SCOPES, stored_by_owner=True)
        memories += authored.memories
        points += authored.index_points
        report = ErasureReport(
            memories=memories,
            index_points=points,
            sessions=len(purged.conversations),
            conversation_messages_cleared=len(purged.conversations),
        )
        _log_erasure("user", owner.tenant_id, actor, target, report)
        return report

    async def _purge(
        self,
        owner: MemoryOwner,
        scopes: tuple[MemoryScope, ...],
        *,
        stored_by_owner: bool = False,
    ) -> _Purged:
        """Delete the memories of ``owner`` at ``scopes``, with their vectors.

        Rows are matched by visibility to ``owner``, or by stored user when
        ``stored_by_owner`` is set. Each row is erased under its own stored owner,
        which always passes the repository's visibility check. The conversations
        the rows came from are collected across every page.
        """
        if self._memories is None:
            return _Purged()
        deleted = 0
        unindexed = 0
        conversations: set[tuple[str, str]] = set()
        for _ in range(_MAX_PASSES):
            rows = await self._memories.search(
                MemoryQuery(
                    owner=owner,
                    scopes=scopes,
                    limit=_PAGE,
                    include_invalid=True,
                    stored_by_owner=stored_by_owner,
                )
            )
            if not rows:
                return _Purged(deleted, unindexed, frozenset(conversations))
            for row in rows:
                unindexed += await self._erasure.erase_memory(row)
                deleted += 1
                principal_id = row.owner.principal_id
                session_id = row.source_session_id or row.owner.session_id
                if principal_id is not None and session_id is not None:
                    conversations.add((principal_id, session_id))
        logger.warning(
            "Memory purge stopped after %d passes for tenant=%s scopes=%s; rows may remain",
            _MAX_PASSES,
            owner.tenant_id,
            ",".join(scope.value for scope in scopes),
        )
        return _Purged(deleted, unindexed, frozenset(conversations))


def _authored_by(memory: Memory, caller: MemoryOwner) -> bool:
    """Return whether ``caller`` is the end user ``memory`` was stored under."""
    return (
        memory.owner.tenant_id == caller.tenant_id
        and memory.owner.user_id is not None
        and memory.owner.user_id == caller.user_id
    )


def _log_erasure(
    kind: str,
    tenant_id: str,
    actor: str,
    target: str,
    report: ErasureReport,
) -> None:
    """Log one erasure with identifiers and counts only, never content."""
    logger.info(
        "Memory erasure kind=%s tenant=%s actor=%s target=%s %s",
        kind,
        tenant_id,
        actor,
        target,
        " ".join(f"{name}={value}" for name, value in report.as_dict().items()),
    )
