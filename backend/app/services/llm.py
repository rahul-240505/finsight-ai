"""Language-model provider interface (ADR-003). Every chat and embedding call goes through here.

`OllamaProvider` talks to the local Ollama server. `FakeProvider` is deterministic and offline,
for tests. Logs carry model name, latency and token counts, never prompt or document text.
"""

import hashlib
import json
import logging
import math
import re
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal, Protocol

import httpx

from app.core.config import Settings, get_settings
from app.core.errors import AppError

logger = logging.getLogger(__name__)

EmbedKind = Literal["document", "query"]
EMBED_BATCH = 32


class ModelUnavailable(AppError):
    status_code, code = 503, "model_unavailable"
    message = "The language model is not reachable. Try again later."


@dataclass(frozen=True)
class ToolCall:
    """A tool the model asked to run. Arguments are untrusted until validated."""

    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ChatResult:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    tool_calls: tuple[ToolCall, ...] = ()


class LLMProvider(Protocol):
    embed_model: str
    chat_model: str

    def embed(self, texts: list[str], kind: EmbedKind) -> list[list[float]]: ...

    def chat(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int,
        tools: list[dict] | None = None,
        num_ctx: int | None = None,
    ) -> ChatResult: ...


class OllamaProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.embed_model = settings.ollama_embed_model
        self.chat_model = settings.ollama_chat_model
        self._client = httpx.Client(
            base_url=settings.ollama_base_url, timeout=settings.ollama_timeout_seconds
        )

    def _post(self, path: str, body: dict) -> dict:
        try:
            response = self._client.post(path, json=body)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            logger.warning("ollama call failed: %s %s", path, type(exc).__name__)
            raise ModelUnavailable() from exc

    def embed(self, texts: list[str], kind: EmbedKind) -> list[list[float]]:
        s = self.settings
        prefix = s.embed_document_prefix if kind == "document" else s.embed_query_prefix
        vectors: list[list[float]] = []
        started = time.perf_counter()
        for i in range(0, len(texts), EMBED_BATCH):
            batch = [prefix + t for t in texts[i : i + EMBED_BATCH]]
            body = {"model": self.embed_model, "input": batch, "truncate": True}
            vectors.extend(self._post("/api/embed", body)["embeddings"])
        if len(vectors) != len(texts) or not all(map(self._valid, vectors)):
            # Seen in practice: a stuck model server returned all-zero vectors with HTTP 200.
            # Storing those would make every search silently return nothing useful.
            logger.error("embed model=%s returned invalid vectors", self.embed_model)
            raise ModelUnavailable("The embedding model returned invalid vectors.")
        logger.info(
            "embed model=%s kind=%s n=%d latency_ms=%.0f",
            self.embed_model,
            kind,
            len(texts),
            (time.perf_counter() - started) * 1000,
        )
        return vectors

    def _valid(self, vector: list[float]) -> bool:
        return (
            len(vector) == self.settings.embed_dim
            and all(math.isfinite(x) for x in vector)
            and any(x != 0 for x in vector)
        )

    def chat(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int,
        tools: list[dict] | None = None,
        num_ctx: int | None = None,
    ) -> ChatResult:
        body: dict[str, Any] = {
            "model": self.chat_model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {
                "temperature": 0,
                "num_predict": max_tokens,
                "num_ctx": num_ctx or self.settings.ollama_num_ctx,
            },
        }
        if tools:
            body["tools"] = tools
        started = time.perf_counter()
        data = self._post("/api/chat", body)
        message = data.get("message") or {}
        calls = []
        for call in message.get("tool_calls") or []:
            fn = call.get("function") or {}
            args = fn.get("arguments")
            if isinstance(args, str):  # some models return JSON text instead of an object
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"_unparsed": args[:200]}
            calls.append(ToolCall(str(fn.get("name", "")), args if isinstance(args, dict) else {}))
        result = ChatResult(
            text=message.get("content") or "",
            model=self.chat_model,
            prompt_tokens=data.get("prompt_eval_count", 0),
            completion_tokens=data.get("eval_count", 0),
            latency_ms=(time.perf_counter() - started) * 1000,
            tool_calls=tuple(calls),
        )
        logger.info(
            "chat model=%s prompt_tokens=%d completion_tokens=%d latency_ms=%.0f",
            result.model,
            result.prompt_tokens,
            result.completion_tokens,
            result.latency_ms,
        )
        return result


_WORD = re.compile(r"[a-z0-9]+")
_SOURCE = re.compile(r'<source id="(S\d+)"[^>]*>\n(.*?)\n</source>', re.DOTALL)


class FakeProvider:
    """Offline stand-in. Embeddings are hashed bags of words, so texts that share words are
    similar and unrelated texts are not. Chat quotes the best-matching sentence of the first
    source and cites it, unless `reply` is set."""

    embed_model = "fake-embed"
    chat_model = "fake-chat"

    def __init__(self, dim: int = 768, reply: str | None = None) -> None:
        self.dim = dim
        self.reply = reply
        self.script: list[Any] = []
        self.offered_tools: list[list[str]] = []  # tool names offered on each chat call
        self.last_messages: list[dict[str, Any]] = []

    def embed(self, texts: list[str], kind: EmbedKind) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def _vector(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for word in _WORD.findall(text.lower()):
            h = int.from_bytes(hashlib.blake2b(word.encode(), digest_size=8).digest(), "big")
            v[h % self.dim] += 1.0 if (h >> 32) & 1 else -1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def chat(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int,
        tools: list[dict] | None = None,
        num_ctx: int | None = None,
    ) -> ChatResult:
        self.last_messages = messages
        self.offered_tools.append([t["function"]["name"] for t in tools or []])
        if self.script:  # scripted turns: a ChatResult, an exception, or f(messages)
            step = self.script.pop(0)
            if callable(step):
                step = step(messages)
            if isinstance(step, BaseException):
                raise step
            return step
        text = self.reply if self.reply is not None else self._extract(messages[-1]["content"])
        return ChatResult(text, self.chat_model, 0, 0, 0.0)

    @staticmethod
    def _extract(prompt: str) -> str:
        """The sentence from the first source that shares most words with the question."""
        found = _SOURCE.search(prompt)
        if found is None:
            return "NOT_ENOUGH_EVIDENCE"
        question = set(_WORD.findall(prompt.rsplit("Question:", 1)[-1].lower()))
        sentences = re.split(r"(?<=[.!?])\s", found.group(2).strip())
        best = max(sentences, key=lambda s: len(question & set(_WORD.findall(s.lower()))))
        return f"{best} [{found.group(1)}]"


@lru_cache
def _ollama() -> OllamaProvider:
    return OllamaProvider(get_settings())


def get_llm() -> LLMProvider:
    """FastAPI dependency; tests override it with a FakeProvider."""
    return _ollama()
