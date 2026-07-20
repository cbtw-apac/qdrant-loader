"""Unit tests for qdrant_loader_core.llm.providers.gemini."""

import importlib
import sys
import types
from importlib import import_module

import pytest


def _make_llm_settings(
    *,
    embeddings_model: str = "gemini-embedding-2",
    chat_model: str = "gemini-2.0-flash",
    vector_size: int | None = 768,
):
    settings_mod = import_module("qdrant_loader_core.llm.settings")
    return settings_mod.LLMSettings(
        provider="gemini",
        base_url=None,
        api_key="fake-key",
        api_version=None,
        headers=None,
        models={"embeddings": embeddings_model, "chat": chat_model},
        tokenizer="none",
        request=settings_mod.RequestPolicy(),
        rate_limits=settings_mod.RateLimitPolicy(),
        embeddings=settings_mod.EmbeddingPolicy(vector_size=vector_size),
        provider_options=None,
    )


def _make_genai_stub(
    *,
    embed_result=None,
    embed_exc=None,
    chat_text="hello",
    chat_exc=None,
    token_count=42,
):
    state: dict[str, object] = {
        "client_kwargs": None,
        "embed_kwargs": None,
        "chat_kwargs": None,
    }

    types_mod = types.SimpleNamespace()

    class Content:
        def __init__(self, *, role="user", parts=None):
            self.role = role
            self.parts = parts or []

    class Part:
        def __init__(self, text=""):
            self.text = text

        @staticmethod
        def from_text(*, text: str) -> "Part":
            return Part(text=text)

    class EmbedContentConfig:
        def __init__(self, *, output_dimensionality=None):
            self.output_dimensionality = output_dimensionality

    class GenerateContentConfig:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    types_mod.Content = Content
    types_mod.Part = Part
    types_mod.EmbedContentConfig = EmbedContentConfig
    types_mod.GenerateContentConfig = GenerateContentConfig

    errors_mod = types.SimpleNamespace()

    class APIError(Exception):
        def __init__(self, msg="", *, code=None):
            super().__init__(msg)
            self.code = code

    errors_mod.APIError = APIError

    vectors = embed_result if embed_result is not None else [[0.1, 0.2], [0.3, 0.4]]

    class _EmbedItem:
        def __init__(self, values):
            self.values = values

    class _EmbedResponse:
        def __init__(self, vals):
            self.embeddings = [_EmbedItem(v) for v in vals]

    class _Usage:
        prompt_token_count = 10
        candidates_token_count = 5
        total_token_count = 15

    class _ChatResponse:
        def __init__(self):
            self.text = chat_text
            self.usage_metadata = _Usage()
            self.model_version = "gemini-2.0-flash-001"

    class _CountTokensResponse:
        total_tokens = token_count

    class _Models:
        def embed_content(self, **kwargs):
            state["embed_kwargs"] = kwargs
            if embed_exc is not None:
                raise embed_exc
            n = len(kwargs.get("contents", []))
            out = vectors[:n] if len(vectors) >= n else vectors
            return _EmbedResponse(out)

        def generate_content(self, **kwargs):
            state["chat_kwargs"] = kwargs
            if chat_exc is not None:
                raise chat_exc
            return _ChatResponse()

        def count_tokens(self, model, contents):
            return _CountTokensResponse()

    class Client:
        def __init__(self, **kwargs):
            state["client_kwargs"] = kwargs
            self.models = _Models()

    genai_mod = types.ModuleType("google.genai")
    genai_mod.Client = Client
    genai_mod.types = types_mod
    genai_mod.errors = errors_mod

    return genai_mod, types_mod, errors_mod, state


def _reload_gemini(monkeypatch, **kwargs):
    genai_mod, types_mod, errors_mod, state = _make_genai_stub(**kwargs)
    google_pkg = sys.modules.get("google") or types.ModuleType("google")
    google_pkg.__path__ = []  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "google", google_pkg)
    monkeypatch.setitem(sys.modules, "google.genai", genai_mod)
    monkeypatch.setitem(sys.modules, "google.genai.types", types_mod)  # type: ignore[arg-type]
    monkeypatch.setitem(sys.modules, "google.genai.errors", errors_mod)  # type: ignore[arg-type]

    target = "qdrant_loader_core.llm.providers.gemini"
    if target in sys.modules:
        del sys.modules[target]
    return importlib.import_module(target), state


@pytest.mark.parametrize(
    "status,expected",
    [
        (408, "TimeoutError"),
        (504, "TimeoutError"),
        (429, "RateLimitedError"),
        (401, "AuthError"),
        (403, "AuthError"),
        (400, "InvalidRequestError"),
        (500, "ServerError"),
    ],
)
def test_map_gemini_exception_by_status(monkeypatch, status, expected):
    mod, _ = _reload_gemini(monkeypatch)
    exc = Exception("boom")
    exc.status_code = status  # type: ignore[attr-defined]
    mapped = mod._map_gemini_exception(exc)
    assert mapped.__class__.__name__ == expected


def test_map_gemini_exception_special_cases(monkeypatch):
    mod, _ = _reload_gemini(monkeypatch)

    assert (
        mod._map_gemini_exception(TimeoutError("t")).__class__.__name__
        == "TimeoutError"
    )
    assert (
        mod._map_gemini_exception(ValueError("x")).__class__.__name__ == "ServerError"
    )

    genai_errors = sys.modules["google.genai.errors"]
    api_exc = genai_errors.APIError("rl", code=429)  # type: ignore[attr-defined]
    assert mod._map_gemini_exception(api_exc).__class__.__name__ == "RateLimitedError"


def test_messages_to_contents_and_fallback(monkeypatch):
    mod, _ = _reload_gemini(monkeypatch)

    system, contents = mod._messages_to_contents(
        [
            {"role": "system", "content": "S1"},
            {"role": "system", "content": "S2"},
            {"role": "assistant", "content": "a"},
            {"role": "user", "content": 42},
            {"role": "user", "content": None},
        ]
    )
    assert system == "S1\nS2"
    assert len(contents) == 2
    assert contents[0].role == "model"
    assert contents[1].role == "user"

    # Cover genai_types=None branch
    original_types = mod.genai_types
    mod.genai_types = None
    try:
        system2, contents2 = mod._messages_to_contents(
            [{"role": "user", "content": "x"}]
        )
        assert system2 is None
        assert contents2 == [{"role": "user", "parts": [{"text": "x"}]}]
    finally:
        mod.genai_types = original_types


def test_token_counter_paths(monkeypatch):
    mod, _ = _reload_gemini(monkeypatch, token_count=99)
    client = sys.modules["google.genai"].Client()

    c = mod._GeminiTokenCounter(client, "m")
    assert c.count("abc") == 99

    c2 = mod._GeminiTokenCounter(None, "m")
    assert c2.count("abc") == 3


@pytest.mark.asyncio
async def test_embeddings_success_and_config(monkeypatch):
    mod, state = _reload_gemini(monkeypatch, embed_result=[[0.1, 0.2]])
    client = sys.modules["google.genai"].Client()

    emb = mod.GeminiEmbeddings(client, "gemini-embedding-2", output_dimensionality=256)
    out = await emb.embed(["doc"])
    assert out == [[0.1, 0.2]]

    kwargs = state["embed_kwargs"]
    assert kwargs is not None
    assert kwargs["model"] == "gemini-embedding-2"
    assert "config" in kwargs


@pytest.mark.asyncio
async def test_embeddings_validation_and_errors(monkeypatch):
    mod, _ = _reload_gemini(monkeypatch)
    client = sys.modules["google.genai"].Client()

    with pytest.raises(NotImplementedError):
        await mod.GeminiEmbeddings(None, "m").embed(["x"])

    with pytest.raises(mod.InvalidRequestError):
        await mod.GeminiEmbeddings(client, "").embed(["x"])

    assert await mod.GeminiEmbeddings(client, "m").embed([]) == []

    exc = Exception("down")
    exc.status_code = 500  # type: ignore[attr-defined]
    mod2, _ = _reload_gemini(monkeypatch, embed_exc=exc)
    client2 = sys.modules["google.genai"].Client()
    with pytest.raises(mod2.ServerError):
        await mod2.GeminiEmbeddings(client2, "m").embed(["x"])

    mod3, _ = _reload_gemini(monkeypatch, embed_result=[[0.1, 0.2]])
    client3 = sys.modules["google.genai"].Client()
    with pytest.raises(mod3.ServerError, match="expected 1:1"):
        await mod3.GeminiEmbeddings(client3, "m").embed(["a", "b"])


@pytest.mark.asyncio
async def test_chat_success_and_forwarding(monkeypatch):
    mod, state = _reload_gemini(monkeypatch, chat_text="ok")
    client = sys.modules["google.genai"].Client()

    chat = mod.GeminiChat(client, "gemini-2.0-flash")
    result = await chat.chat(
        [{"role": "system", "content": "S"}, {"role": "user", "content": "Hi"}],
        model="gemini-pro",
        temperature=0.7,
        top_p=0.8,
        max_tokens=100,
    )

    assert result["text"] == "ok"
    assert result["usage"]["total_tokens"] == 15
    assert result["model"] == "gemini-2.0-flash-001"

    kwargs = state["chat_kwargs"]
    assert kwargs is not None
    assert kwargs["model"] == "gemini-pro"
    assert "config" in kwargs


@pytest.mark.asyncio
async def test_chat_validation_and_errors(monkeypatch):
    mod, _ = _reload_gemini(monkeypatch)
    client = sys.modules["google.genai"].Client()

    with pytest.raises(NotImplementedError):
        await mod.GeminiChat(None, "m").chat([{"role": "user", "content": "x"}])

    with pytest.raises(mod.InvalidRequestError):
        await mod.GeminiChat(client, "").chat([{"role": "user", "content": "x"}])

    exc = Exception("rl")
    exc.status_code = 429  # type: ignore[attr-defined]
    mod2, _ = _reload_gemini(monkeypatch, chat_exc=exc)
    client2 = sys.modules["google.genai"].Client()
    with pytest.raises(mod2.RateLimitedError):
        await mod2.GeminiChat(client2, "m").chat([{"role": "user", "content": "x"}])


def test_provider_clients_tokenizer_and_vertex_options(monkeypatch):
    mod, state = _reload_gemini(monkeypatch)

    settings = _make_llm_settings()
    settings.provider_options = {
        "vertexai": True,
        "project": "p1",
        "location": "us-central1",
    }
    provider = mod.GeminiProvider(settings)

    assert isinstance(provider.embeddings(), mod.GeminiEmbeddings)
    assert isinstance(provider.chat(), mod.GeminiChat)
    assert isinstance(provider.tokenizer(), mod._GeminiTokenCounter)

    kwargs = state["client_kwargs"]
    assert kwargs is not None
    assert kwargs["api_key"] == "fake-key"
    assert kwargs["vertexai"] is True
    assert kwargs["project"] == "p1"
    assert kwargs["location"] == "us-central1"


def test_provider_when_genai_unavailable(monkeypatch):
    mod, _ = _reload_gemini(monkeypatch)
    original_genai = mod.genai
    mod.genai = None
    try:
        provider = mod.GeminiProvider(_make_llm_settings())
        assert provider._client is None
    finally:
        mod.genai = original_genai


@pytest.mark.asyncio
async def test_provider_roundtrip_embed_and_chat(monkeypatch):
    mod, _ = _reload_gemini(
        monkeypatch, embed_result=[[1.0, 2.0, 3.0]], chat_text="pong"
    )
    provider = mod.GeminiProvider(_make_llm_settings())

    vectors = await provider.embeddings().embed(["hello"])
    assert vectors == [[1.0, 2.0, 3.0]]

    resp = await provider.chat().chat([{"role": "user", "content": "ping"}])
    assert resp["text"] == "pong"
