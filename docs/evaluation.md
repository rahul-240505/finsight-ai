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

### 2026-11-26 · Anomaly scoring: Isolation Forest vs baselines (synthetic, labelled injections)
- Milestone: ML scoring · Version: 0.4.0 (uncommitted, on top of the data & SQL commit) · model `iforest-20261126145149`
- Dataset: `transactions_500k.csv` (seed 42) with `labels_500k.csv` (5,014 injected anomaly rows, 1.0%). Time split: train 2025-01-01..09-30 (373,642 rows, 3,719 positives) · validation 10-01..11-30 (84,080 / 855) · test 12-01..12-31 (42,278 / 440)
- Machine: i5-12500H, 15 GiB RAM (CPU only)
- Command: `cd backend && PYTHONPATH=. uv run python ../ml/training/train_isolation_forest.py --csv ../data/transactions_500k.csv --labels ../data/labels_500k.csv --register`
- Setup: 8 features, all computed from each account's *earlier* transactions only. IsolationForest(n_estimators=200, max_samples=256, random_state=42) fitted on train without labels. Threshold = max F1 on validation; test reported once. Model chosen by validation PR-AUC.
- Result (test set):

| Scorer | Val PR-AUC | Test PR-AUC (95% bootstrap CI) | ROC-AUC | Precision | Recall | F1 | Precision in top 1% |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Random | 0.0102 | 0.0110 [0.0097, 0.0130] | 0.507 | 0.011 | 0.216 | 0.021 | 0.012 |
| Rule: amount_z | 0.2101 | 0.2015 [0.1661, 0.2400] | 0.848 | 0.485 | 0.182 | 0.265 | 0.232 |
| **Isolation Forest (served)** | **0.6824** | **0.6581 [0.6144, 0.6998]** | 0.948 | 0.709 | 0.554 | 0.622 | 0.642 |
| Hybrid (max of forest and amount_z percentiles) | 0.6147 | 0.5687 [0.5213, 0.6144] | 0.953 | 0.666 | 0.543 | 0.598 | 0.602 |

- Isolation Forest test confusion at threshold: TP 244 · FP 100 · FN 196; flag rate 0.81%. Recall by type (test): burst 0.717 · high_risk_merchant 0.404 · large_amount 0.327 · night_unfamiliar 0.143. The amount rule catches large_amount at 0.959 but bursts at 0.0.
- Fit 0.76-0.82 s; feature build 0.41 s for 500k rows (2.3 s before the datetime fix below).
- Notes: the hybrid was designed after viewing the Isolation Forest's per-type test results (the same weakness is visible on validation: large_amount recall 0.475). It was then selected *against* by the pre-set rule (validation PR-AUC) and is not served. Labels come from the same generator as the data, so these numbers measure detection of these four injected patterns, not real-world fraud detection.

### 2026-11-26 · Risk scoring through the API (500k rows)
- Milestone: ML scoring · Version: 0.4.0 · model `iforest-20261126145149`
- Dataset: demo user's 500k-row dataset (same file as above)
- Command: `curl -X POST /api/v1/risk-assessments -d '{"dataset_id": …}'` ×3 (re-scoring replaces previous scores); review queue `GET /api/v1/risk-assessments?dataset_id=…&limit=50` ×3
- Result: scoring 18.84 / 20.64 / 22.98 s (median 20.64 s); 500,000 scored, 7,904 flagged (1.58%). Review queue page 0.013-0.015 s (earlier model version, same query). Train/serve consistency: flags served for December rows = 344 (TP 244, FP 100), identical to the training script's test result.
- Flag rate by month (served): Jan 8.30% · Feb 1.41% · Mar 1.16% · Apr 1.04% · May-Dec 0.81-0.92%.
- Notes: **cold start**: accounts with little history are over-flagged (January). Not visible in the December test set. Planned fix: an explicit "insufficient history" state instead of a flag, evaluated on validation first.

### 2026-11-26 · Supervised fraud classification (public credit-card dataset)
- Milestone: ML scoring · experiment, not served
- Dataset: OpenML 1597 (284,807 card transactions, 492 frauds = 0.173%). OpenML's copy has no Time column; split by original row order: train 60% (360 frauds) · validation 20% (57) · test 20% (75)
- Machine: i5-12500H, 15 GiB RAM (CPU only)
- Command: `cd backend && PYTHONPATH=. uv run python ../ml/experiments/creditcard_supervised.py`
- Setup: V1..V28 + Amount. Logistic regression (StandardScaler in a Pipeline, class_weight="balanced") and HistGradientBoosting (class_weight="balanced", random_state=42). Threshold = max F1 on validation; test once. 1,000-sample paired bootstrap on test.
- Result (test):

| Model | Val PR-AUC | Test PR-AUC (95% CI) | ROC-AUC | Precision | Recall | TP / FP / FN | Fit time |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Random | — | 0.0012 | 0.463 | 0.001 | 0.400 | 30 / 23,775 / 45 | — |
| Rule: Amount | — | 0.0014 | 0.382 | 0.003 | 0.040 | 3 / 1,022 / 72 | — |
| Logistic regression | 0.7725 | 0.7438 [0.6302, 0.8521] | 0.982 | 0.926 | 0.667 | 50 / 4 / 25 | 0.71 s |
| Gradient boosting | 0.7579 | 0.7529 [0.6509, 0.8396] | 0.972 | 0.877 | 0.667 | 50 / 7 / 25 | 10.95 s |

- Gradient boosting − logistic regression, test PR-AUC: 95% CI [-0.0714, +0.0875] → no detectable difference with 75 test frauds; logistic regression is simpler, 15× faster to fit and better on validation.
- Notes: large amounts are *not* a fraud signal here (Amount rule ≈ random). Dataset download from OpenML took ~11 minutes (66 MB cache in `data/openml`, git-ignored).

### 2026-11-26 · Test suite after ML milestone
- Version: 0.4.0 · Command: `cd backend && uv run pytest` (3 runs)
- Result: 105 passed, 0 failed, 0 skipped. Wall time 8.90 / 8.94 / 8.87 s (median 8.90 s), final run after all Phase 3 changes.

### 2026-11-26 · Document Q&A, run 1 (prompt `rag-v1`, 200-word chunks) — superseded by run 2
- Milestone: document Q&A · Version: 0.5.0 (uncommitted, on top of 5b59038)
- Dataset: `eval/policy_corpus.json`: 6 fictional policy PDFs, 17 pages. `eval/rag_questions.jsonl`: 42 answerable (expected file + page + keywords), 10 unanswerable, 3 prompt-injection probes aimed at a page with a planted instruction; answerable/unanswerable alternate dev/test (injection probes all test).
- Machine: i5-12500H, 15 GiB RAM, RTX 4050 6 GB · Ollama `nomic-embed-text` + `qwen3.5:4b` (temperature 0, thinking off, num_ctx 4096) · Postgres + Qdrant in local Docker
- Command: `cd backend && PYTHONPATH=. uv run python ../eval/run_rag_eval.py` (first version of the script)
- Retrieval (all 42 answerable, top 5, in-memory cosine on the same embeddings):

| Chunking (words/overlap) | Chunks | Recall@1 | Recall@3 | Recall@5 | MRR@5 |
| --- | --- | --- | --- | --- | --- |
| 100 / 20 | 26 | 0.786 | 1.000 | 1.000 | 0.877 |
| 200 / 40 | 17 | 0.738 | 0.952 | 1.000 | 0.845 |
| 350 / 60 | 17 | 0.738 | 0.952 | 1.000 | 0.845 |

- End to end with 200/40 and a gate of 0.689 (best balanced accuracy on dev): answered 36/42 answerable (85.7%), keyword accuracy 85.7%, citation accuracy 100% of answered, citation precision 0.75; 10/10 unanswerable declined (all by the gate); injection 3/3 passed. With the gate off: 42/42 answered, keyword accuracy 100%, citation precision 0.78; 9/10 unanswerable declined by the model.
- Problems found: (1) the gate blocked 6 answerable questions, because answerable and unanswerable best-match scores overlap (dev: weakest answerable 0.648, strongest unanswerable 0.678); (2) one unanswerable question ("overdraft fee") came back as prose ("The provided sources do not contain information…") citing all five sources, so it counted as answered; (3) answers were padded to four sentences with loosely related facts, lowering citation precision.
- Notes: 200 and 350 words give identical chunks because every page is under 200 words. The first evaluation attempts failed because the Ollama server returned all-zero embeddings and hung on chat (HTTP 200 / 500 after 120 s); unloading and reloading the models fixed it, and the provider now rejects zero, non-finite and wrong-size vectors.

### 2026-11-26 · Document Q&A, run 2 (prompt `rag-v2`, chunking and gate chosen on dev)
- Milestone: document Q&A · Version: 0.5.0 (uncommitted, on top of 5b59038)
- Dataset, machine, models: as run 1
- Changes after run 1: prompt `rag-v2` (1-3 sentences, only facts that answer the question, the refusal token "and nothing else"); prose refusals ("the sources do not contain…") treated as declined; chunk size chosen by dev MRR@5; gate rule changed to "the highest cut-off that blocks no answerable dev question" (blocking a real answer loses it; a let-through question costs one model call that the model and the citation check can still decline).
- Command: `cd backend && PYTHONPATH=. uv run python ../eval/run_rag_eval.py`
- Retrieval by split (identical embeddings to run 1):

| Chunking | Dev Recall@1 | Dev MRR@5 | Test Recall@1 | Test Recall@3 | Test MRR@5 |
| --- | --- | --- | --- | --- | --- |
| **100 / 20 (chosen on dev)** | 0.762 | 0.865 | 0.809 | 1.000 | 0.889 |
| 200 / 40 | 0.714 | 0.841 | 0.762 | 0.905 | 0.849 |
| 350 / 60 | 0.714 | 0.841 | 0.762 | 0.905 | 0.849 |

- Gate chosen on dev: **0.6404** (the balanced-accuracy rule would give 0.687).
- End to end, gate on (through Postgres + Qdrant + Ollama):

| Split | Answered (answerable) | Keyword accuracy | Citation accuracy | Citation precision | Unanswerable declined | Injection probes passed | Answer latency p50 / p95 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Dev | 21/21 | 1.000 | 1.000 | 1.000 | 5/5 (4 gate, 1 model) | — | 1.42 / 1.93 s |
| Test | 21/21 | 1.000 | 1.000 | 0.960 | 5/5 (5 gate) | 3/3 | 1.28 / 1.79 s |
| All | 42/42 | 1.000 | 1.000 | 0.980 | 10/10 (9 gate, 1 model) | 3/3 | 1.32 / 1.87 s |

- Gate off: same answers for answerable questions (42/42, precision 0.980); 10/10 unanswerable declined by the model itself (gate saves 9 model calls out of 10 on unanswerable questions; a gated question returned in 16-19 ms in the eval).
- Indexing (embed + Postgres + Qdrant, per PDF, one run): 58-279 ms; the first file includes model warm-up.
- Definitions: *keyword accuracy* = answered and contains every expected keyword; *citation accuracy* = at least one citation on the expected page; *citation precision* = citations on the expected page ÷ all citations; *injection passed* = the planted sentence does not appear in the answer.
- Notes: **not a held-out benchmark.** The corpus and questions were written by the same author, the questions are close paraphrases, and the run-2 prompt and refusal changes were made after seeing run-1 results on all questions (the dev/test split protects the chunk-size and gate choices only). Treat it as a regression suite: a later change that lowers these numbers is a real regression. Latencies are over the questions that reached the chat model in one run (46 gate on, 55 gate off), warm model.

### 2026-11-26 · Live API check, document Q&A
- Version: 0.5.0 · `uvicorn app.main:app` on the host, demo user, `data/policies/card-dispute-procedure.pdf` (3 pages, 5 chunks)
- Result: upload 201 in 1.31 s; same file again → existing document with `Idempotent-Replayed: true`; "How long does a customer have to report a disputed card payment?" → answered, cites page 2 (score 0.919), 2.02 s; "What is the overdraft fee?" → `not_enough_evidence` (`no_relevant_passages`), 0.027 s. A second user: same question → 0 passages retrieved; owner's document via GET, DELETE and `document_ids` → 404. Owner DELETE → 204; Qdrant points for the document 5 → 0. Server log contained no document text.

### 2026-11-26 · Test suite after document Q&A milestone
- Version: 0.5.0 · Command: `cd backend && uv run pytest` (3 runs, Ollama running)
- Result: 147 passed, 0 failed, 0 skipped (includes 1 live-Ollama test, skipped in CI). Wall time 13.50 / 13.13 / 13.11 s (median 13.13 s).

### 2026-11-26 · Rate limiter fail-open cost with Redis unreachable
- Milestone: background jobs · Version: 0.6.0 (uncommitted, on top of 75b1341)
- Command: one pipelined `INCR` against `127.0.0.1:1` (nothing listening), redis-py 8.2.0, 0.5 s socket timeouts
- Result: default client 3.995 s per call (built-in retries with back-off) · `retry=Retry(NoBackoff(), 0)` 0.001 s. In the test suite the fail-open test took 17.09 s before the fix and under 0.5 s after.
- Notes: the limiter and the job queue's Redis clients now never retry, and the limiter skips Redis for 5 s after an error.

### 2026-11-26 · Background jobs, live (API + RQ worker on the host)
- Milestone: background jobs · Version: 0.6.0 (uncommitted, on top of 75b1341)
- Dataset: `data/transactions_500k.csv` (500,000 rows, seed 42), imported by a dedicated benchmark user (deleted afterwards); query indexes present
- Machine: i5-12500H, 15 GiB RAM · Postgres, Redis in local Docker · `uvicorn app.main:app` + `python -m app.worker` (RQ 3.0.0)
- Command: benchmark client (httpx): POST, then poll `GET /api/v1/jobs/{id}` every 0.2 s; during each import, `/health` and `GET /api/v1/datasets` probed every 0.1 s from a second client
- Result, import (3 runs, dataset deleted between runs): accepted (`202`) in 0.143 / 0.123 / 0.129 s (median **0.129 s**, previously a 20.52 s synchronous request); job finished 12.70 / 14.33 / 16.24 s after the POST (median **14.33 s**). During the imports: `/health` p50 1.8 / 1.8 / 1.9 ms (max 6.9 ms, 123-158 probes per run); dataset list p50 5.3-5.5 ms.
- Result, scoring the same dataset (3 runs): accepted in 0.039 / 0.014 / 0.511 s (median 0.039 s); job 26.22 / 35.67 / 30.88 s (median 30.88 s). `pg_stat_user_tables` then showed 1,000,753 dead rows in `risk_assessments` and 500,000 in `transactions`; after `VACUUM ANALYZE` two more runs took 22.45 / 24.12 s (synchronous baseline 20.6 s).
- Result, duplicate submission: the same file posted twice in a row with different Idempotency-Keys → both 202 with the **same job id**; 1 dataset created.
- Result, rate limit: 32 questions in a row → 30 × 200 then 429 (`rate_limited`, `Retry-After: 22`).
- Notes: job times include the poll interval and the fork per job. The import job times rise run to run (dead rows from deleting the previous 500k-row dataset; same effect as the 2026-11-26 import entry). Re-scoring leaves 500k dead rows per run until autovacuum.

### 2026-11-26 · Worker crash recovery, live
- Version: 0.6.0 · worker started with `JOB_STALE_AFTER_SECONDS=20`
- Procedure: queue a 500k-row import; 4 s later `kill -9` the work-horse process and the worker; wait 22 s; start the worker again.
- Result: after the kill the job stayed `running` (attempt 1, 0 datasets). On start the worker's sweep re-delivered it ("dataset_import, running"); attempt 2 started 0.25 s later and succeeded 13.8 s after that; exactly **1 dataset**, no partial rows from the killed attempt (its transaction never committed). Upload folder empty afterwards.
- Also observed: killing only the worker parent does *not* stop a running work horse; in a first attempt the orphaned horse finished the job (succeeded, attempt 1).

### 2026-11-26 · Test suite after background-jobs milestone
- Version: 0.6.0 · Command: `cd backend && uv run pytest` (3 runs, Ollama running)
- Result: 166 passed, 0 failed, 0 skipped. Wall time 23.69 / 17.52 / 17.87 s (median 17.87 s).
