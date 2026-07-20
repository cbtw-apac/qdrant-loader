from __future__ import annotations

import pytest
from qdrant_loader.config.state import StateManagementConfig
from qdrant_loader.core.state.session import (
    dispose_engine,
    initialize_engine_and_session,
)
from sqlalchemy.pool import StaticPool


@pytest.mark.asyncio
async def test_sqlite_in_memory_uses_static_pool() -> None:
    config = StateManagementConfig(database_path=":memory:")
    engine, _ = initialize_engine_and_session(config)
    try:
        assert isinstance(engine.sync_engine.pool, StaticPool)
    finally:
        await dispose_engine(engine)


@pytest.mark.asyncio
async def test_sqlite_file_based_does_not_use_static_pool(tmp_path) -> None:
    db_path = tmp_path / "state.db"
    config = StateManagementConfig(database_path=str(db_path))
    engine, _ = initialize_engine_and_session(config)
    try:
        assert not isinstance(engine.sync_engine.pool, StaticPool)
    finally:
        await dispose_engine(engine)
