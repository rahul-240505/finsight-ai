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

### 2026-11-26 · Test suite: authentication and access control
- Milestone: core backend · Version: 0.2.0 (uncommitted, on top of 64b819e)
- Dataset: none (test fixtures create users and datasets per test, rolled back afterwards)
- Machine: i5-12500H, 15 GiB RAM · Data stores: local Docker (PostgreSQL 17, separate `finsight_test` database)
- Command: `cd backend && uv run pytest` (3 runs); `uv run pytest -m integration`; `uv run pytest -m "not integration"`
- Result: 41 passed, 0 failed, 0 skipped (17 unit, 24 integration). Wall time 3.63 / 3.66 / 3.69 s, median 3.66 s. Access-control coverage: 7 private routes × unauthenticated → 401, viewer write → 403, non-admin role change → 403, cross-user read and delete → 404, foreign vs missing ID responses identical.
- Notes: most of the time is Argon2id hashing (deliberately slow). One third-party deprecation warning (Starlette TestClient suggests `httpx2`).

### 2026-11-26 · Live check: auth, IDOR and CSRF against a running server
- Milestone: core backend · Version: 0.2.0
- Dataset: two demo users, one dataset (deleted afterwards)
- Machine: as above · `uvicorn app.main:app` on localhost
- Command: `curl` sequence: register ×2, login ×2, create dataset as user A, read as A and B, DELETE with `Origin: https://evil.test`, wrong password vs unknown email
- Result: register 201/201, login 200/200, owner read 200, other user read 404, cross-site DELETE 403 (dataset still present, 200), wrong password and unknown email both 401 with the same message. Cookie: `HttpOnly; Max-Age=43200; Path=/; SameSite=lax; Secure`.
- Notes: single run; behavioural check, not a benchmark.
