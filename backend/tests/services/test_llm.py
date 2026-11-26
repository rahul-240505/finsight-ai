"""Model provider checks: bad model output is rejected, not stored. The live test needs Ollama."""

import json

import httpx
import pytest

from app.core.config import get_settings
from app.services.llm import ModelUnavailable, OllamaProvider


def provider_with(handler) -> OllamaProvider:
    provider = OllamaProvider(get_settings())
    provider._client = httpx.Client(
        base_url="http://ollama.test", transport=httpx.MockTransport(handler)
    )
    return provider


@pytest.mark.parametrize(
    "vector",
    [[0.0] * 768, [float("nan")] + [0.1] * 767, [0.1] * 10],
    ids=["all-zero", "nan", "wrong-size"],
)
def test_invalid_embeddings_are_rejected(vector: list[float]) -> None:
    # json.dumps writes NaN literally (as a buggy server might); httpx's json= refuses to.
    body = json.dumps({"embeddings": [vector]}).encode()
    provider = provider_with(lambda _: httpx.Response(200, content=body))
    with pytest.raises(ModelUnavailable):
        provider.embed(["text"], "document")


def test_unreachable_server_is_a_503_error() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(ModelUnavailable) as caught:
        provider_with(refuse).chat([{"role": "user", "content": "hi"}], 5)
    assert caught.value.status_code == 503


@pytest.mark.ollama
def test_live_models_embed_and_answer() -> None:
    provider = OllamaProvider(get_settings())
    [vector] = provider.embed(["Disputes must be reported within 60 days."], "document")
    assert len(vector) == get_settings().embed_dim
    reply = provider.chat([{"role": "user", "content": "Reply with the single word OK."}], 10)
    assert "ok" in reply.text.lower() and reply.completion_tokens > 0
