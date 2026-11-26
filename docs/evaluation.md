# Evaluation log

Every benchmark and evaluation result for FinSight AI, with the exact command and setup used. Entries are append-only; superseded results are marked, not deleted.

### 2026-11-24 · Test suite and CI
- Milestone: foundation · Version: 0.1.0
- Dataset: none (no data yet)
- Machine: i5-12500H, 15 GiB RAM, RTX 4050 6 GB (local) · GitHub-hosted `ubuntu-latest` (CI) · Data stores: local Docker / CI service containers
- Command: `cd backend && uv run pytest` (local) · GitHub Actions workflow `ci.yml` on `main` (CI)
- Result: 8 tests passed locally (7 unit + 1 integration against real Postgres/Redis/Qdrant). CI job `backend` succeeded; job time 32 s including container start-up (single run).
- Notes: one third-party warning (Starlette suggests `httpx2` for TestClient); not from our code.

### 2026-11-24 · /ready behaviour with a stopped dependency
- Milestone: foundation · Version: 0.1.0
- Dataset: none
- Machine: local (as above) · Data stores: local Docker
- Command: `docker stop finsight-redis-1` then `curl localhost:8000/ready`; `docker start` then `curl` again
- Result: Redis stopped → HTTP 503, `{"redis":"down"}`, response in 0.047 s (connection refused, single run). Redis restarted → HTTP 200, all `ok`, no app restart. Log line contained only `redis (ConnectionError)`.
- Notes: a hanging (not refusing) dependency would take up to `READY_TIMEOUT_SECONDS` (2 s); not measured yet.

### 2026-11-24 · Ollama model smoke test (ADR-003)
- Milestone: foundation · Version: 0.1.0
- Dataset: one fixed prompt each (chat, one-tool call, embed query)
- Machine: i5-12500H, 15 GiB RAM, RTX 4050 Laptop 6 GB · Ollama 0.40.17
- Command: `python3 scripts/ollama_smoke.py` (stdlib script, `think: false`, `temperature: 0`, `num_predict: 120`)
- Result: qwen3.5:4b (Q4_K_M, 3.3 GB) chat median wall 1.47 s, median generation 49.8 tok/s (3 warm runs after 1 warm-up). One-tool prompt → correct call `get_transaction({"transaction_id": "tx-1042"})` (1 run). nomic-embed-text: 768 dims, median 10 ms per query (3 warm runs). `ollama ps`: both 100% GPU; VRAM 4024 / 6141 MiB.
- Notes: Ollama default context loaded as 4096 (chat) and 2048 (embed). One tool-call run is a smoke test, not a reliability measure; the agent eval in agent evaluation will measure that.

### 2026-11-26 · Ollama smoke test (refactored script)
- Milestone: foundation · Version: 0.1.0
- Dataset: one fixed prompt each (chat, one-tool call, embed query)
- Machine: i5-12500H, 15 GiB RAM, RTX 4050 Laptop 6 GB · Ollama 0.40.17
- Command: `python3 scripts/ollama_smoke.py` (models from `OLLAMA_*` env vars, defaults qwen3.5:4b and nomic-embed-text)
- Result: chat median wall 0.99 s, median generation 49.9 tok/s (3 warm runs after 1 warm-up, `num_predict: 120`). Tool call correct: `get_transaction({"transaction_id": "tx-1042"})` (1 run). Embedding: 768 dims, median 9 ms (3 runs).
- Notes: the chat prompt is shorter than in the 2026-11-24 entry, so wall time is not comparable; generation speed (tok/s) is. Single invocation of the script.
