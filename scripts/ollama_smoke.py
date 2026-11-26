"""Smoke test for the configured Ollama models: chat speed, one tool call, embedding size.

Standard library only, so it runs without the backend environment:

    python3 scripts/ollama_smoke.py

Reads OLLAMA_BASE_URL, OLLAMA_CHAT_MODEL and OLLAMA_EMBED_MODEL from the environment.
"""

import json
import os
import statistics
import time
import urllib.request

BASE = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
CHAT = os.environ.get("OLLAMA_CHAT_MODEL", "qwen3.5:4b")
EMBED = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")
RUNS = 3

if not BASE.startswith(("http://", "https://")):
    raise SystemExit(f"OLLAMA_BASE_URL must be http(s), got {BASE!r}")

GET_TRANSACTION_TOOL = {
    "type": "function",
    "function": {
        "name": "get_transaction",
        "description": "Fetch one transaction by its ID",
        "parameters": {
            "type": "object",
            "properties": {"transaction_id": {"type": "string"}},
            "required": ["transaction_id"],
        },
    },
}


def post(path: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    # S310: BASE is checked to be http(s) at import time, so file:// URLs can't reach here.
    req = urllib.request.Request(BASE + path, data, {"Content-Type": "application/json"})  # noqa: S310
    with urllib.request.urlopen(req, timeout=300) as resp:  # noqa: S310
        return json.loads(resp.read())


def chat(messages: list[dict], **extra: object) -> dict:
    body = {"model": CHAT, "messages": messages, "stream": False, "think": False, **extra}
    return post("/api/chat", body)


def bench_chat() -> None:
    messages = [{"role": "user", "content": "In two sentences, why use NUMERIC for money?"}]
    chat(messages)  # warm-up: loads the model, excluded from timings
    walls, speeds = [], []
    for _ in range(RUNS):
        start = time.perf_counter()
        resp = chat(messages, options={"temperature": 0, "num_predict": 120})
        walls.append(time.perf_counter() - start)
        speeds.append(resp["eval_count"] / (resp["eval_duration"] / 1e9))
    print(
        f"chat: median wall {statistics.median(walls):.2f} s, "
        f"median generation {statistics.median(speeds):.1f} tok/s over {RUNS} warm runs"
    )


def check_tool_call() -> None:
    messages = [{"role": "user", "content": "Look up transaction tx-1042 for me."}]
    resp = chat(messages, tools=[GET_TRANSACTION_TOOL], options={"temperature": 0})
    calls = resp["message"].get("tool_calls") or []
    found = [(c["function"]["name"], c["function"]["arguments"]) for c in calls]
    print("tool calls:", found or "NONE")


def bench_embed() -> None:
    query = "search_query: What is the approval limit for wire transfers?"
    post("/api/embed", {"model": EMBED, "input": "warm-up"})
    times = []
    for _ in range(RUNS):
        start = time.perf_counter()
        resp = post("/api/embed", {"model": EMBED, "input": query})
        times.append(time.perf_counter() - start)
    dims = len(resp["embeddings"][0])
    print(f"embed: {dims} dims, median {statistics.median(times) * 1000:.0f} ms over {RUNS} runs")


if __name__ == "__main__":
    bench_chat()
    check_tool_call()
    bench_embed()
