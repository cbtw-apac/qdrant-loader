import asyncio
import os

import pytest
from fastapi import HTTPException
from qdrant_loader.webhooks.auth import (
    _get_webhook_secret_from_env,
    get_webhook_secret,
    verify_webhook_token,
    webhook_auth_configured,
)


@pytest.fixture(autouse=True)
def clear_secret_cache():
    _get_webhook_secret_from_env.cache_clear()
    yield
    _get_webhook_secret_from_env.cache_clear()


@pytest.fixture(autouse=True)
def clear_webhook_env(monkeypatch):
    """Ensure no leftover WEBHOOK_* env vars leak between tests."""
    for key in list(os.environ):
        if key.startswith("WEBHOOK_SECRET") or key == "WEBHOOK_ENABLE_COGNITO_JWT":
            monkeypatch.delenv(key, raising=False)


def test_webhook_auth_configured_false_when_nothing_set():
    assert webhook_auth_configured() is False


def test_webhook_auth_configured_false_when_secret_is_empty_string(monkeypatch):
    # AIKH-2368: WEBHOOK_SECRET="" (present but empty) must be treated as unset.
    monkeypatch.setenv("WEBHOOK_SECRET", "")
    assert webhook_auth_configured() is False


def test_webhook_auth_configured_true_with_global_secret(monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", "secret")
    assert webhook_auth_configured() is True


def test_webhook_auth_configured_true_with_secrets_json(monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRETS", '{"project1": "secret"}')
    assert webhook_auth_configured() is True


def test_webhook_auth_configured_false_when_secrets_json_is_empty_dict(monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRETS", "{}")
    assert webhook_auth_configured() is False


def test_webhook_auth_configured_false_when_secrets_json_is_malformed(monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRETS", "{not valid json")
    assert webhook_auth_configured() is False


def test_webhook_auth_configured_false_when_secrets_json_values_empty(monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRETS", '{"project1": ""}')
    assert webhook_auth_configured() is False


def test_webhook_auth_configured_true_with_project_scoped_secret(monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET_MYPROJECT", "secret")
    assert webhook_auth_configured() is True


def test_webhook_auth_configured_true_with_cognito_enabled(monkeypatch):
    monkeypatch.setenv("WEBHOOK_ENABLE_COGNITO_JWT", "true")
    assert webhook_auth_configured() is True


def test_get_webhook_secret_global(monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", "global-secret")
    assert asyncio.run(get_webhook_secret()) == "global-secret"


def test_get_webhook_secret_per_project(monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", "global-secret")
    monkeypatch.setenv("WEBHOOK_SECRETS", '{"project1": "project-secret"}')
    assert asyncio.run(get_webhook_secret(project_id="project1")) == "project-secret"
    assert asyncio.run(get_webhook_secret(project_id="other")) == "global-secret"


def test_verify_webhook_token_accepts_valid_secret(monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", "secret")
    asyncio.run(
        verify_webhook_token(
            project_id=None,
            webhook_token="secret",
            authorization=None,
        )
    )


def test_verify_webhook_token_rejects_invalid(monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", "secret")
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            verify_webhook_token(
                project_id=None,
                webhook_token="wrong",
                authorization=None,
            )
        )
    assert exc_info.value.status_code == 401


def test_verify_webhook_token_honors_cognito_flag_set_after_import(monkeypatch):
    # AIKH-2368: the Cognito flag must be read fresh at request time, not
    # frozen at module import (serve_cmd imports this module before .env
    # is loaded), otherwise a valid JWT would be rejected as a plain secret.
    monkeypatch.setenv("WEBHOOK_ENABLE_COGNITO_JWT", "true")
    monkeypatch.setenv("WEBHOOK_SECRET", "secret")

    async def fake_validate_token(cls, token):
        return {"sub": "user"}

    monkeypatch.setattr(
        "qdrant_loader.webhooks.auth.CognitoJWTValidator.validate_token",
        classmethod(fake_validate_token),
    )

    fake_jwt = "header.payload.signature"
    asyncio.run(
        verify_webhook_token(
            project_id=None,
            webhook_token=None,
            authorization=f"Bearer {fake_jwt}",
        )
    )
