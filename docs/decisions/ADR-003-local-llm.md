# ADR-003: Local Ollama behind a provider interface; qwen3.5:4b + nomic-embed-text

- Status: Accepted · Date: 2026-11-24

## Context
The project runs fully locally: no paid or hosted APIs. Target hardware: a laptop GPU with 6 GB VRAM and 16 GB RAM. Need one instruction-tuned chat model that can do tool calling (investigation agent) and grounded answers (document Q&A), plus one embedding model. Tests must not depend on a running model.

## Options
- **Chat:** qwen3.5:4b (3.3 GB, Q4_K_M, tools + optional thinking) · qwen3:4b (tools) · phi4-mini 3.8B (no clear tool-calling support) · gemma 4B variants (reported bias toward always emitting tool calls) · 7–8B models (~5 GB at Q4: would spill off the 6 GB GPU).
- **Embeddings:** nomic-embed-text (137M params, 274 MB, 768 dims, English-focused) · qwen3-embedding:0.6b (multilingual, larger) · mxbai-embed-large (1024 dims, 512-token limit).
- **Integration:** call Ollama directly everywhere vs a provider interface with Ollama and fake implementations.

## Decision
- Chat: **qwen3.5:4b** with thinking off by default (`think: false`) for speed and short grounded answers.
- Embeddings: **nomic-embed-text** (768 dims). Requires task prefixes: `search_document: ` for chunks, `search_query: ` for questions.
- All calls go through `app/services/llm.py` with timeouts and max tokens; a fake provider for tests. Model names live only in `Settings` (`OLLAMA_CHAT_MODEL`, `OLLAMA_EMBED_MODEL`).
- Model files are large (≈3.6 GB total); set `OLLAMA_MODELS` to a partition with enough space if needed.

## Evidence (docs/evaluation.md, 2026-11-24)
Both models 100% on GPU (4.0 / 6.1 GB VRAM). Chat: median 1.47 s wall, 49.8 tok/s generation (3 warm runs, 120-token cap). Tool call on a one-tool prompt: correct name and args. Embedding: 768 dims, median 10 ms.

## Consequences
- Fast and free, private data stays local; quality is below large hosted models, so RAG and the agent must rely on validation, not model obedience.
- Ollama's default context was 4096 (chat) and 2048 (embed); the RAG module must set `num_ctx` explicitly and size chunks under the embed limit.
- Changing the embedding model means re-embedding every document (store model name with each vector).

## Revisit when
RAG or agent evaluation shows the 4B model failing citations or tool calls; more VRAM becomes available; a hosted model is allowed (swap via the provider interface).
