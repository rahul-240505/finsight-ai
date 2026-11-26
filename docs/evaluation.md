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

### 2026-11-26 · Synthetic dataset
- Milestone: data & SQL · Version: 0.3.0 (uncommitted, on top of c38af4a)
- Dataset: `python3 scripts/generate_synthetic.py --rows 500000 --seed 42` → `data/transactions_500k.csv` (37.7 MB) + `data/labels_500k.csv`
- Machine: i5-12500H, 15 GiB RAM
- Command: as above; generated twice and compared with `md5sum`
- Result: 500,000 rows, 5,000 accounts, currencies USD 342,444 / GBP 79,098 / EUR 78,458, dates 2025-01-01 to 2025-12-31. 5,014 rows belong to injected anomalies (burst 3,227 · large_amount 610 · night_unfamiliar 598 · high_risk_merchant 579). Identical MD5 on both runs (deterministic). Generation ≈ 5 s.
- Notes: anomaly labels are kept in a separate file and never imported; they exist to evaluate anomaly scoring.

### 2026-11-26 · CSV import throughput (500k rows, through the API)
- Milestone: data & SQL · Version: 0.3.0
- Dataset: `transactions_500k.csv` (seed 42)
- Machine: i5-12500H, 15 GiB RAM · PostgreSQL 17 in Docker (data on NVMe, /home) · `uvicorn app.main:app` single process
- Command: `curl -X POST "/api/v1/datasets?name=…" -H "Content-Type: text/csv" -H "Idempotency-Key: …" --data-binary @data/transactions_500k.csv` (`%{time_total}`), dataset deleted between runs
- Result:
  - Before query indexes (PK + UNIQUE(dataset_id, external_ref) only): 10.78 / 10.68 / 10.92 s → median **10.78 s** (≈ 46k rows/s).
  - After adding 3 query indexes, table vacuumed before each run: 20.88 / 16.13 / 20.52 s → median **20.52 s**.
  - Parse + validate alone (in-process, 3 runs): 3.58 / 3.70 / 3.72 s → median 3.70 s.
  - Replay with the same Idempotency-Key: HTTP 201 in 0.089 s, `Idempotent-Replayed: true`, no new rows. Same file with a new key: HTTP 409 with the existing dataset ID.
- Notes: an earlier set of indexed runs without VACUUM between delete and re-import gave 15.8 / 19.7 / 32.2 s (dead index entries accumulating); superseded by the vacuumed runs above. Indexed-run variance is high; treat the ~2× write cost as approximate. The import is synchronous today; moving it to a background worker is planned.

### 2026-11-26 · Query latency before/after indexes (EXPLAIN ANALYZE)
- Milestone: data & SQL · Version: 0.3.0 · Migration `b65db3d037db` adds the indexes
- Dataset: one owner, 500,000 transactions (seed 42); `ANALYZE transactions` before each set
- Machine: as above
- Command: `cd backend && PYTHONPATH=. uv run python ../scripts/benchmark_queries.py --owner-email demo@example.com --label before|after` (1 warm-up + 5 runs each, server-side execution time)
- Result (median ms, before → after):

| Query | Before | After | Plan after |
| --- | --- | --- | --- |
| Newest page (LIMIT 51) | 43.281 | 0.023 | Index Scan `ix_transactions_owner_time` |
| Keyset page at row 250,000 | 35.349 | 0.021 | Index Scan `ix_transactions_owner_time` |
| OFFSET 250,000 page | 119.355 | 21.591 | Index Scan (still walks 250k entries) |
| One account's history | 24.235 | 0.037 | Index Scan `ix_transactions_owner_account_time` |
| One category, one month | 27.413 | 0.062 | Index Scan `ix_transactions_owner_category_time` |
| Summary by currency (all rows) | 54.385 | 53.872 | Parallel Seq Scan (unchanged) |

- Index build time (3 indexes, `alembic upgrade`): ≈ 2.1 s wall. Index sizes: 28 / 37 / 36 MB.
- API end-to-end (curl, 3 runs, after indexes): `GET /transactions?limit=50` 0.014 / 0.006 / 0.006 s; `GET /analytics/summary` 0.65 / 0.50 / 0.48 s.
- Notes: "before" plans were Parallel Seq Scan + Sort for every query. Indexes don't help the full-table summary; it needs pre-aggregation or caching if it must be faster. Plain `CREATE INDEX` blocks writes while it builds; on a live system use `CREATE INDEX CONCURRENTLY`.

### 2026-11-26 · Test suite after data & SQL milestone
- Milestone: data & SQL · Version: 0.3.0 (uncommitted, on top of c38af4a)
- Dataset: fixtures (small generated CSVs per test, rolled back)
- Machine: i5-12500H, 15 GiB RAM · PostgreSQL 17 in Docker
- Command: `cd backend && uv run pytest` (3 runs); `-m "not integration"`; `-m integration`
- Result: 83 passed, 0 failed, 0 skipped (39 unit, 44 integration). Wall time 7.18 / 6.96 / 7.19 s, median 7.18 s.
- Notes: covers row validation rules, all-or-nothing import, idempotent replay, key reuse (422), duplicate file (409), size/type limits (413/415), preview, cascade delete, composite-FK owner check, keyset pagination, filters, per-currency summary, owner isolation, and 11 private routes → 401.
