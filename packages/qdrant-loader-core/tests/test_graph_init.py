from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import qdrant_loader_core.graph as graph_module


@pytest.fixture(autouse=True)
def reset_graph_store_singleton():
    graph_module._graph_store = None
    yield
    graph_module._graph_store = None


@pytest.mark.asyncio
async def test_get_graph_store_raises_when_falkor_extra_not_installed():
    with patch.object(graph_module, "FalkorGraphStore", None):
        with pytest.raises(ModuleNotFoundError, match="requires the 'graph' extra"):
            await graph_module.get_graph_store()


@pytest.mark.asyncio
async def test_get_graph_store_creates_with_defaults():
    mock_store = MagicMock()
    mock_store_cls = MagicMock(return_value=mock_store)

    with (
        patch.object(graph_module, "FalkorGraphStore", mock_store_cls),
        patch.object(graph_module, "init_schema", AsyncMock()) as mock_init,
    ):
        result = await graph_module.get_graph_store()

    mock_store_cls.assert_called_once_with(
        host="localhost",
        port=6379,
        password=None,
        graph_name="default_graph",
        max_connections=10,
    )
    mock_init.assert_awaited_once_with(mock_store)
    assert result is mock_store


@pytest.mark.asyncio
async def test_get_graph_store_creates_with_custom_params():
    mock_store = MagicMock()
    mock_store_cls = MagicMock(return_value=mock_store)

    with (
        patch.object(graph_module, "FalkorGraphStore", mock_store_cls),
        patch.object(graph_module, "init_schema", AsyncMock()),
    ):
        result = await graph_module.get_graph_store(
            host="myhost",
            port=1234,
            password="secret",
            graph_name="mygraph",
            max_connections=5,
        )

    mock_store_cls.assert_called_once_with(
        host="myhost",
        port=1234,
        password="secret",
        graph_name="mygraph",
        max_connections=5,
    )
    assert result is mock_store


@pytest.mark.asyncio
async def test_get_graph_store_returns_cached_singleton_on_second_call():
    mock_store = MagicMock()
    mock_store_cls = MagicMock(return_value=mock_store)

    with (
        patch.object(graph_module, "FalkorGraphStore", mock_store_cls),
        patch.object(graph_module, "init_schema", AsyncMock()),
    ):
        first = await graph_module.get_graph_store()
        second = await graph_module.get_graph_store()

    mock_store_cls.assert_called_once()
    assert first is second
