"""Regression tests for `qdrant-loader serve` webhook-secret fail-closed behavior.

AIKH-2368: with no WEBHOOK_SECRET / WEBHOOK_SECRETS / WEBHOOK_SECRET_<PROJECT_ID>
and Cognito disabled, `serve` must refuse to start with a clear config error
*before* any DB engine/uvicorn/asyncio resources are created - not crash later
with an unhandled asyncio/SQLAlchemy error.
"""

from __future__ import annotations

import asyncio
import os

import pytest
from click import ClickException
from qdrant_loader.cli.commands.serve_cmd import _serve_main


@pytest.fixture(autouse=True)
def clear_webhook_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith("WEBHOOK_SECRET") or key == "WEBHOOK_ENABLE_COGNITO_JWT":
            monkeypatch.delenv(key, raising=False)


def test_serve_fails_closed_before_state_manager_init(monkeypatch):
    """No webhook secret configured: serve must raise ClickException before
    ever reaching StateManager.initialize() (i.e. before any DB engine, queue,
    or uvicorn/asyncio resource is created)."""
    monkeypatch.setattr(
        "qdrant_loader.cli.config_loader.load_config_with_workspace",
        lambda *a, **k: None,
    )

    initialize_calls = []

    async def fake_initialize(self):
        initialize_calls.append(self)

    monkeypatch.setattr(
        "qdrant_loader.core.state.state_manager.StateManager.initialize",
        fake_initialize,
    )

    with pytest.raises(
        ClickException, match="Webhook authentication is not configured"
    ):
        asyncio.run(_serve_main(None, None, None, "INFO"))

    assert initialize_calls == []
